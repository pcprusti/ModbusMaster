#!/usr/bin/env python
"""Tkinter Modbus RTU master with editable register values and frame tracing."""

import math
import queue
import threading
import tkinter as tk
from tkinter import ttk

from pymodbus.client import ModbusSerialClient
from pymodbus.framer import FramerRTU, FramerType
from pymodbus.pdu.bit_message import (
	ReadCoilsRequest,
	ReadDiscreteInputsRequest,
	WriteMultipleCoilsRequest,
	WriteSingleCoilRequest,
)
from pymodbus.pdu.register_message import (
	ReadHoldingRegistersRequest,
	ReadInputRegistersRequest,
	WriteSingleRegisterRequest,
	WriteMultipleRegistersRequest,
)
from serial.tools import list_ports


FUNCTIONS = {
	"01 Read Coils (0x)": 1,
	"02 Read Discrete Inputs (1x)": 2,
	"03 Read Holding Registers (4x)": 3,
	"04 Read Input Registers (3x)": 4,
	"05 Write Single Coil": 5,
	"06 Write Single Register": 6,
	"15 Write Multiple Coils": 15,
	"16 Write Multiple Registers": 16,
}
ADDRESS_BASES = {1: 1, 2: 10001, 3: 40001, 4: 30001, 5: 1, 6: 40001, 15: 1, 16: 40001}
READ_FUNCTIONS = {1, 2, 3, 4}
COIL_FUNCTIONS = {1, 2, 5, 15}
WRITE_FUNCTIONS = {5, 6, 15, 16}
SINGLE_FUNCTIONS = {5, 6}


class ModbusMasterApp:
	"""Provide a graphical interface for Modbus RTU read and write requests."""

	def __init__(self, root):
		"""Create the connection controls, request form, and data/frame views."""
		self.root = root
		self.events = queue.Queue()
		self.worker = None
		self.client = None
		self.connecting = False
		self.request_busy = False
		self.root.title("Modbus RTU Master")
		self.root.geometry("1000x700")
		self.root.minsize(850, 600)
		self.root.configure(background="#eef2f1")
		self._configure_styles()
		self._build_ui()
		self.refresh_ports()
		self.root.after(100, self._process_events)
		self.root.protocol("WM_DELETE_WINDOW", self._close)

	def _configure_styles(self):
		"""Set a compact, high-contrast style for the master interface."""
		style = ttk.Style()
		style.theme_use("clam")
		style.configure("TFrame", background="#eef2f1")
		style.configure("TLabelframe", background="#eef2f1", padding=8)
		style.configure("TLabelframe.Label", background="#eef2f1", foreground="#263b38")
		style.configure("TLabel", background="#eef2f1", foreground="#263b38")
		style.configure("TCheckbutton", background="#eef2f1")
		style.configure("Title.TLabel", font=("Segoe UI", 17, "bold"))
		style.configure("TButton", padding=(10, 6))
		style.configure("Treeview", rowheight=25, font=("Consolas", 10))
		style.configure("Treeview.Heading", font=("Segoe UI", 9, "bold"))

	def _build_ui(self):
		"""Lay out serial settings, Modbus controls, values, and RTU frames."""
		main = ttk.Frame(self.root, padding=14)
		main.pack(fill="both", expand=True)
		ttk.Label(main, text="Modbus RTU Master", style="Title.TLabel").pack(
			anchor="w", pady=(0, 10)
		)

		connection = ttk.LabelFrame(main, text="Connection")
		connection.pack(fill="x", pady=(0, 8))
		self._build_connection_controls(connection)

		request = ttk.LabelFrame(main, text="Request")
		request.pack(fill="x", pady=(0, 8))
		self._build_request_controls(request)

		body = ttk.Panedwindow(main, orient="horizontal")
		body.pack(fill="both", expand=True)
		data_panel = ttk.LabelFrame(body, text="Register / Coil Values")
		trace_panel = ttk.Frame(body)
		body.add(data_panel, weight=3)
		body.add(trace_panel, weight=2)
		self._build_value_table(data_panel)
		self._refresh_value_rows(preserve=False)
		self._build_trace_views(trace_panel)

		self.status_var = tk.StringVar(value="Ready")
		ttk.Label(main, textvariable=self.status_var, padding=(2, 8)).pack(anchor="w")

	def _build_connection_controls(self, parent):
		"""Create RTU port, baud, framing, and refresh controls."""
		self.mode_var = tk.StringVar(value="RTU")
		self.port_var = tk.StringVar()
		self.baud_var = tk.StringVar(value="9600")
		self.data_bits_var = tk.StringVar(value="8")
		self.stop_bits_var = tk.StringVar(value="1")
		self.parity_var = tk.StringVar(value="N")

		self.mode_box = ttk.Combobox(
			parent, textvariable=self.mode_var, values=("RTU",), state="readonly", width=8
		)
		self._field(parent, 0, "Mode", self.mode_box)
		port_box = ttk.Combobox(parent, textvariable=self.port_var, state="readonly", width=13)
		self._field(parent, 1, "COM port", port_box)
		self.port_box = port_box
		self.refresh_button = ttk.Button(parent, text="Refresh", command=self.refresh_ports)
		self.refresh_button.grid(
			row=1, column=2, padx=(0, 8), pady=(0, 2), sticky="ew"
		)
		self.baud_box = ttk.Combobox(
			parent, textvariable=self.baud_var,
			values=("1200", "2400", "4800", "9600", "19200", "38400", "57600", "115200"),
			state="readonly", width=10,
		)
		self._field(parent, 3, "Baud", self.baud_box)
		self.data_bits_box = ttk.Combobox(
			parent, textvariable=self.data_bits_var, values=("5", "6", "7", "8"),
			state="readonly", width=8,
		)
		self._field(parent, 4, "Data bits", self.data_bits_box)
		self.stop_bits_box = ttk.Combobox(
			parent, textvariable=self.stop_bits_var, values=("1", "1.5", "2"),
			state="readonly", width=8,
		)
		self._field(parent, 5, "Stop bits", self.stop_bits_box)
		self.parity_box = ttk.Combobox(
			parent, textvariable=self.parity_var, values=("N", "E", "O"),
			state="readonly", width=8,
		)
		self._field(parent, 6, "Parity", self.parity_box)
		self.connection_inputs = [
			self.mode_box, self.port_box, self.refresh_button, self.baud_box,
			self.data_bits_box, self.stop_bits_box, self.parity_box,
		]
		self.connect_button = ttk.Button(
			parent, text="Connect", command=self.toggle_connection
		)
		self.connect_button.grid(row=1, column=7, padx=4, pady=(0, 2), sticky="ew")
		indicator = ttk.Frame(parent)
		indicator.grid(row=1, column=8, padx=(8, 4), pady=(0, 2), sticky="w")
		self.led = tk.Canvas(
			indicator, width=18, height=18, background="#eef2f1", highlightthickness=0
		)
		self.led.pack(side="left", padx=(0, 5))
		self.led_dot = self.led.create_oval(3, 3, 15, 15, fill="#8b9996", outline="")
		self.connection_text = tk.StringVar(value="Disconnected")
		ttk.Label(indicator, textvariable=self.connection_text).pack(side="left")
		parent.columnconfigure(1, weight=1)

	@staticmethod
	def _field(parent, column, label, widget):
		"""Place a labeled input in a two-row settings column."""
		ttk.Label(parent, text=label).grid(
			row=0, column=column, sticky="w", padx=(4, 8), pady=(0, 3)
		)
		widget.grid(row=1, column=column, sticky="ew", padx=(4, 8), pady=(0, 2))

	def _build_request_controls(self, parent):
		"""Create slave, function, address, quantity, and Send controls."""
		self.slave_var = tk.StringVar(value="1")
		self.function_var = tk.StringVar(value="04 Read Input Registers (3x)")
		self.address_var = tk.StringVar(value="30001")
		self.count_var = tk.StringVar(value="1")
		self.continuous_var = tk.BooleanVar(value=False)
		self.interval_var = tk.StringVar(value="1000")

		self._field(parent, 0, "Slave ID", ttk.Entry(
			parent, textvariable=self.slave_var, width=8
		))
		function_box = ttk.Combobox(
			parent, textvariable=self.function_var, values=tuple(FUNCTIONS),
			state="readonly", width=29,
		)
		self._field(parent, 1, "Function", function_box)
		function_box.bind("<<ComboboxSelected>>", self._on_function_change)
		self._field(parent, 2, "First register / address", ttk.Entry(
			parent, textvariable=self.address_var, width=18
		))
		self._field(parent, 3, "Number of values", ttk.Spinbox(
			parent, textvariable=self.count_var, from_=1, to=2000, width=9
		))
		self.count_box = parent.grid_slaves(row=1, column=3)[0]
		self.address_var.trace_add("write", self._on_table_range_change)
		self.count_var.trace_add("write", self._on_table_range_change)
		self.send_button = ttk.Button(
			parent, text="Send", command=self.send_request, state="disabled"
		)
		self.send_button.grid(
			row=1, column=4, sticky="ew", padx=(4, 8), pady=(0, 2)
		)
		ttk.Checkbutton(
			parent,
			text="Send continuously",
			variable=self.continuous_var,
		).grid(row=1, column=5, sticky="w", padx=(4, 8), pady=(0, 2))
		ttk.Label(parent, text="Time between sends (ms)").grid(
			row=0, column=6, sticky="w", padx=(4, 8), pady=(0, 3)
		)
		ttk.Spinbox(
			parent,
			textvariable=self.interval_var,
			from_=1,
			to=3600000,
			increment=100,
			width=10,
		).grid(row=1, column=6, sticky="ew", padx=(4, 8), pady=(0, 2))
		parent.columnconfigure(1, weight=1)
		self._refresh_value_rows(preserve=False)
		self._on_function_change()

	def _build_value_table(self, parent):
		"""Create the scrollable, inline-editable address/value table."""
		container = ttk.Frame(parent)
		container.pack(fill="both", expand=True, padx=4, pady=4)
		self.values_tree = ttk.Treeview(
			container, columns=("address", "value"), show="headings", selectmode="browse"
		)
		self.values_tree.heading("address", text="Address")
		self.values_tree.heading("value", text="Value")
		self.values_tree.column("address", width=145, anchor="w", stretch=True)
		self.values_tree.column("value", width=145, anchor="w", stretch=True)
		scrollbar = ttk.Scrollbar(
			container, orient="vertical", command=self.values_tree.yview
		)
		self.values_tree.configure(yscrollcommand=scrollbar.set)
		self.values_tree.pack(side="left", fill="both", expand=True)
		scrollbar.pack(side="right", fill="y")
		self.values_tree.bind("<Double-1>", self._edit_value_cell)

	def _build_trace_views(self, parent):
		"""Create the raw hexadecimal request and response panes."""
		request_box = ttk.LabelFrame(parent, text="Request frame (RTU hex)")
		request_box.pack(fill="x", padx=(8, 0), pady=(0, 8))
		self.request_text = self._trace_text(request_box, height=4)
		response_box = ttk.LabelFrame(parent, text="Response frame (RTU hex)")
		response_box.pack(fill="both", expand=True, padx=(8, 0))
		self.response_text = self._trace_text(response_box, height=10)

	@staticmethod
	def _trace_text(parent, height):
		"""Create a read-only hex frame text view."""
		text = tk.Text(
			parent, height=height, wrap="word", font=("Consolas", 10),
			background="#f5fbfa", foreground="#173c38", relief="flat", padx=8, pady=7,
		)
		text.pack(fill="both", expand=True, padx=5, pady=5)
		text.configure(state="disabled")
		return text

	def refresh_ports(self):
		"""Rescan serial ports and retain the current selection if possible."""
		ports = [port.device for port in list_ports.comports()]
		current = self.port_var.get()
		self.port_box.configure(values=ports)
		if current in ports:
			self.port_var.set(current)
		elif ports:
			self.port_var.set(ports[0])
		else:
			self.port_var.set("")
			self.status_var.set("No serial ports found")

	def toggle_connection(self):
		"""Open or close the selected serial connection in a worker thread."""
		if self.connecting or self.request_busy:
			return
		if self.client is not None:
			self.connecting = True
			self.connect_button.configure(state="disabled")
			self.send_button.configure(state="disabled")
			self.status_var.set("Disconnecting...")
			self.worker = threading.Thread(
				target=self._disconnect_client, args=(self.client,), daemon=True
			)
			self.worker.start()
			return

		if not self.port_var.get():
			self.status_var.set("Select a COM port before connecting")
			return
		try:
			settings = {
				"port": self.port_var.get(),
				"baudrate": int(self.baud_var.get()),
				"bytesize": int(self.data_bits_var.get()),
				"stopbits": float(self.stop_bits_var.get()),
				"parity": self.parity_var.get(),
			}
		except (ValueError, tk.TclError) as exc:
			self.status_var.set(f"Invalid connection setting: {exc}")
			return

		self.connecting = True
		self.connect_button.configure(text="Connecting...", state="disabled")
		self._set_connection_inputs_enabled(False)
		self.status_var.set(f"Opening {settings['port']}...")
		self.worker = threading.Thread(
			target=self._connect_client, args=(settings,), daemon=True
		)
		self.worker.start()

	def _connect_client(self, settings):
		"""Open a persistent Modbus serial client and report the result."""
		client = None
		try:
			client = ModbusSerialClient(
				port=settings["port"],
				framer=FramerType.RTU,
				baudrate=settings["baudrate"],
				bytesize=settings["bytesize"],
				stopbits=settings["stopbits"],
				parity=settings["parity"],
				timeout=1,
				retries=1,
			)
			if not client.connect():
				raise ConnectionError(f"Could not open {settings['port']}")
			self.events.put(("connected", client, settings["port"]))
			client = None
		except Exception as exc:
			self.events.put(("connect_failure", str(exc)))
		finally:
			if client is not None:
				client.close()

	def _disconnect_client(self, client):
		"""Close the persistent serial client and report disconnect completion."""
		try:
			client.close()
			error = None
		except Exception as exc:
			error = str(exc)
		self.events.put(("disconnected", error))

	def _set_connection_inputs_enabled(self, enabled):
		"""Enable serial controls only when no client is connected or opening."""
		for widget in self.connection_inputs:
			if widget is self.mode_box or widget in {
				self.port_box, self.baud_box, self.data_bits_box,
				self.stop_bits_box, self.parity_box,
			}:
				widget.configure(state="readonly" if enabled else "disabled")
			else:
				widget.configure(state="normal" if enabled else "disabled")

	def _function_code(self):
		"""Return the selected Modbus function code."""
		return FUNCTIONS[self.function_var.get()]

	def _on_function_change(self, _event=None):
		"""Apply function-specific quantity limits and refresh table rows."""
		function = self._function_code()
		self.address_var.set(f"{ADDRESS_BASES[function]:05d}")
		if function in SINGLE_FUNCTIONS:
			self.count_var.set("1")
			self.count_box.configure(state="disabled")
		else:
			self.count_box.configure(state="normal")
		self._refresh_value_rows(preserve=False)

	def _on_table_range_change(self, *_args):
		"""Update visible row addresses when the range fields change."""
		if hasattr(self, "values_tree"):
			self._refresh_value_rows(preserve=True)

	def _refresh_value_rows(self, preserve=True):
		"""Rebuild the value table for the entered first address and count."""
		if not hasattr(self, "values_tree"):
			return
		try:
			first = self._parse_integer(self.address_var.get())
			count = int(self.count_var.get())
			if count < 1 or count > 2000:
				return
		except (ValueError, tk.TclError):
			return

		old_values = {}
		if preserve:
			for item in self.values_tree.get_children():
				old_values[int(item)] = self.values_tree.set(item, "value")
		self.values_tree.delete(*self.values_tree.get_children())
		is_write = self._function_code() in WRITE_FUNCTIONS
		for index in range(count):
			value = old_values.get(index, "0" if is_write else "")
			self.values_tree.insert(
				"", "end", iid=str(index), values=(first + index, value)
			)

	def _edit_value_cell(self, event):
		"""Edit a write value by double-clicking its table cell."""
		if self._function_code() not in WRITE_FUNCTIONS:
			return
		if self.values_tree.identify("region", event.x, event.y) != "cell":
			return
		if self.values_tree.identify_column(event.x) != "#2":
			return
		item = self.values_tree.identify_row(event.y)
		if not item:
			return
		bounds = self.values_tree.bbox(item, "value")
		if not bounds:
			return
		editor = ttk.Entry(self.values_tree)
		editor.place(x=bounds[0], y=bounds[1], width=bounds[2], height=bounds[3])
		editor.insert(0, self.values_tree.set(item, "value"))
		editor.select_range(0, "end")
		editor.focus_set()

		def commit(_event=None):
			if editor.winfo_exists():
				self.values_tree.set(item, "value", editor.get().strip())
				editor.destroy()

		editor.bind("<Return>", commit)
		editor.bind("<FocusOut>", commit)

	@staticmethod
	def _parse_integer(value):
		"""Parse a decimal or 0x-prefixed integer from a form field."""
		value = value.strip()
		return int(value, 16) if value.lower().startswith("0x") else int(value, 10)

	def _address_offset(self, function, entered_address):
		"""Convert a standard reference address to the zero-based PDU offset."""
		base = ADDRESS_BASES[function]
		if entered_address >= base:
			offset = entered_address - base
		elif entered_address == base - 1:
			offset = 0
		else:
			offset = entered_address
		if not 0 <= offset <= 65535:
			raise ValueError("Address must map to a 16-bit Modbus offset")
		return offset

	def _write_values(self, function, count):
		"""Read and validate all values entered for a write request."""
		rows = self.values_tree.get_children()
		if len(rows) < count:
			raise ValueError("The value table does not contain enough rows")
		values = []
		for item in rows[:count]:
			raw = self.values_tree.set(item, "value").strip()
			if function in COIL_FUNCTIONS:
				if raw.lower() in {"1", "true", "on"}:
					values.append(True)
				elif raw.lower() in {"0", "false", "off"}:
					values.append(False)
				else:
					raise ValueError("Coil values must be 0/1 or true/false")
			else:
				value = self._parse_integer(raw)
				if not 0 <= value <= 65535:
					raise ValueError("Register values must be between 0 and 65535")
				values.append(value)
		return values

	def _make_request(self, function, address, count, slave, values):
		"""Construct a pymodbus request for the selected function code."""
		if function == 1:
			return ReadCoilsRequest(address=address, count=count, dev_id=slave)
		if function == 2:
			return ReadDiscreteInputsRequest(address=address, count=count, dev_id=slave)
		if function == 3:
			return ReadHoldingRegistersRequest(
				address=address, count=count, dev_id=slave
			)
		if function == 4:
			return ReadInputRegistersRequest(address=address, count=count, dev_id=slave)
		if function == 5:
			return WriteSingleCoilRequest(
				address=address, bits=[values[0]], dev_id=slave
			)
		if function == 6:
			return WriteSingleRegisterRequest(
				address=address, registers=[values[0]], dev_id=slave
			)
		if function == 15:
			return WriteMultipleCoilsRequest(
				address=address, bits=values, dev_id=slave
			)
		if function == 16:
			return WriteMultipleRegistersRequest(
				address=address, registers=values, dev_id=slave
			)
		raise ValueError("Unsupported function code")

	@staticmethod
	def _frame_hex(message):
		"""Build an RTU frame with its CRC for display."""
		frame = FramerRTU(None).buildFrame(message)
		return frame.hex(" ").upper()

	def send_request(self):
		"""Validate the form, build the RTU request, and start a worker thread."""
		if self.request_busy:
			return
		if self.client is None:
			self.status_var.set("Connect to a COM port before sending a request")
			return
		try:
			slave = self._parse_integer(self.slave_var.get())
			if not 1 <= slave <= 247:
				raise ValueError("Slave ID must be between 1 and 247")
			function = self._function_code()
			entered_address = self._parse_integer(self.address_var.get())
			address = self._address_offset(function, entered_address)
			count = 1 if function in SINGLE_FUNCTIONS else int(self.count_var.get())
			limit = 2000 if function in {1, 2, 15} else 125
			if not 1 <= count <= limit:
				raise ValueError(f"Quantity must be between 1 and {limit}")
			self._refresh_value_rows(preserve=True)
			values = self._write_values(function, count) if function in WRITE_FUNCTIONS else []
			request = self._make_request(function, address, count, slave, values)
			request_frame = self._frame_hex(request)
		except (ValueError, KeyError, tk.TclError) as exc:
			self.status_var.set(f"Input error: {exc}")
			return

		self._set_trace(self.request_text, request_frame)
		self._set_trace(self.response_text, "Waiting for response...")
		self.status_var.set(f"Sending function {function:02d} to slave {slave}...")
		self.request_busy = True
		self.send_button.configure(state="disabled")
		self.connect_button.configure(state="disabled")
		self.worker = threading.Thread(
			target=self._execute_request,
			args=(self.client, request, request_frame, function, count),
			daemon=True,
		)
		self.worker.start()

	def _execute_request(self, client, request, request_frame, function, count):
		"""Execute one request on a worker thread and queue its response."""
		try:
			response = client.execute(False, request)
			response_frame = self._frame_hex(response)
			if response.isError():
				self.events.put(("error", request_frame, response_frame, str(response)))
				return
			result_values = []
			if function in {1, 2}:
				result_values = [int(value) for value in response.bits[:count]]
			elif function in {3, 4}:
				result_values = response.registers[:count]
			self.events.put(("success", request_frame, response_frame, result_values))
		except Exception as exc:
			self.events.put(("failure", request_frame, str(exc)))

	@staticmethod
	def _set_trace(widget, value):
		"""Replace the contents of a read-only RTU frame pane."""
		widget.configure(state="normal")
		widget.delete("1.0", "end")
		widget.insert("1.0", value)
		widget.configure(state="disabled")

	def _process_events(self):
		"""Update the request/response panes and values on the Tk thread."""
		while True:
			try:
				event = self.events.get_nowait()
			except queue.Empty:
				break
			if event[0] == "connected":
				_, client, port = event
				self.client = client
				self.connecting = False
				self.led.itemconfigure(self.led_dot, fill="#218c5b")
				self.connection_text.set("Connected")
				self.connect_button.configure(text="Disconnect", state="normal")
				self.send_button.configure(state="normal")
				self.status_var.set(f"Connected to {port}")
			elif event[0] == "connect_failure":
				self.connecting = False
				self.client = None
				self.led.itemconfigure(self.led_dot, fill="#8b9996")
				self.connection_text.set("Disconnected")
				self.connect_button.configure(text="Connect", state="normal")
				self._set_connection_inputs_enabled(True)
				self.status_var.set(f"Connection failed: {event[1]}")
			elif event[0] == "disconnected":
				self.connecting = False
				self.client = None
				self.led.itemconfigure(self.led_dot, fill="#8b9996")
				self.connection_text.set("Disconnected")
				self.connect_button.configure(text="Connect", state="normal")
				self._set_connection_inputs_enabled(True)
				self.status_var.set(
					f"Disconnect error: {event[1]}" if event[1] else "Disconnected"
				)
			elif event[0] == "success":
				_, request_frame, response_frame, values = event
				self._set_trace(self.request_text, request_frame)
				self._set_trace(self.response_text, response_frame)
				if values:
					for index, value in enumerate(values):
						item = str(index)
						if self.values_tree.exists(item):
							self.values_tree.set(item, "value", str(value))
				self.status_var.set("Request completed successfully")
				self._finish_request()
			elif event[0] == "error":
				_, request_frame, response_frame, message = event
				self._set_trace(self.request_text, request_frame)
				self._set_trace(self.response_text, response_frame)
				self.status_var.set(f"Modbus exception: {message}")
				self._finish_request()
			elif event[0] == "failure":
				_, request_frame, message = event
				self._set_trace(self.request_text, request_frame)
				self._set_trace(self.response_text, f"No valid response\n{message}")
				self.status_var.set(f"Communication error: {message}")
				self._finish_request()
		self.root.after(100, self._process_events)

	def _finish_request(self):
		"""Unlock controls and schedule another request when continuous mode is on."""
		self.request_busy = False
		self.send_button.configure(state="normal" if self.client is not None else "disabled")
		self.connect_button.configure(state="normal")
		if self.continuous_var.get() and self.client is not None:
			try:
				interval = float(self.interval_var.get())
				if not math.isfinite(interval) or not 1 <= interval <= 3600000:
					raise ValueError
			except ValueError:
				self.continuous_var.set(False)
				self.status_var.set("Continuous send stopped: interval must be 1 to 3600000 ms")
				return
			self.root.after(round(interval), self._send_continuous_request)

	def _send_continuous_request(self):
		"""Send the next request if continuous mode remains enabled and connected."""
		if self.continuous_var.get() and self.client is not None:
			self.send_request()

	def _close(self):
		"""Close the active serial client before shutting down the GUI."""
		if self.client is not None:
			self.client.close()
		self.root.destroy()


if __name__ == "__main__":
	root = tk.Tk()
	app = ModbusMasterApp(root)
	root.mainloop()
