# Modbus RTU Master

`ModbusMaster.py` is a Tkinter Modbus RTU master for sending register and coil requests over a serial COM port. It displays editable values and the RTU request/response frames in hexadecimal, including CRC bytes.

## Requirements

- Python 3 with Tkinter enabled
- PyModbus 3.15.0 and pyserial (installed from `requirement.txt`)
- The packages listed in `requirement.txt`

Install the external packages from this folder:

```powershell
py -m pip install -r requirement.txt
```

Tkinter is included with most standard Python installations. On Windows, install Python with Tcl/Tk support if Tkinter is unavailable.

## Run

From this folder, launch the application:

```powershell
py ModbusMaster.py
```

## Use

1. Select the COM port and serial settings. Defaults are 9600 baud, 8 data bits, 1 stop bit, and no parity.
2. Click **Connect**. The connection indicator turns green when the serial port opens successfully.
3. Select the slave ID, function code, starting address, and quantity. Defaults are slave 1, function 04 (Read Input Registers), address `30001`, and quantity 1.
4. For write functions, double-click a value cell to enter a coil value (`0`/`1` or `false`/`true`) or a register value (decimal or `0x`-prefixed hexadecimal).
5. Click **Send** to execute one request. The request and response frame panes show the RTU frames.

The function dropdown supports:

| Code | Function |
| --- | --- |
| 01 | Read Coils |
| 02 | Read Discrete Inputs |
| 03 | Read Holding Registers |
| 04 | Read Input Registers |
| 05 | Write Single Coil |
| 06 | Write Single Register |
| 15 | Write Multiple Coils |
| 16 | Write Multiple Registers |

Addresses use standard one-based Modbus reference notation. For example, input register `30001` maps to protocol offset 0. The displayed starting address updates when the function changes.

Select **Send continuously** to repeat the current request after each response. The interval is in milliseconds and defaults to `1000`. Uncheck it to stop after the current request finishes.

## Troubleshooting

- If the port list is empty, connect the serial adapter and click **Refresh**; install its driver if Windows does not detect it.
- If the connection fails, ensure the selected COM port is not in use by another application.
- If the device does not respond, verify the slave ID, baud rate, data bits, parity, and stop bits against the device configuration.
- The LED indicates that the serial port is open; a green LED does not guarantee that the selected slave is responding to Modbus requests.
## Modbus Master GUI
<img width="1242" height="907" alt="image" src="https://github.com/user-attachments/assets/e6c7a06d-9f00-4c6d-acad-90e3a8f16012" />

