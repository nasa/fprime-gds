# GUI Test Procedure

This document is a test suite for the Graphical User Interface (GUI) of the F' GDS. Testing will be conducted by running the [Ref app](https://github.com/nasa/fprime/tree/master/Ref) in order to test the F' GDS functionalities through a browser.

## Set up

The below steps ensure that the environment is set up correctly, with the correct version of the F' GDS installed.
1. Checkout https://github.com/nasa/fprime and https://github.com/fprime-community/fprime-gds at the branch to be tested.
2. Set up the F' virtual environment
```
cd <path/to>/fprime
python -m venv ~/fprime-venv
source ~/fprime-venv/bin/activate
pip install -r requirements.txt
```
3. Install the fprime-gds version to be tested 
```
cd <path/to>/fprime-gds
pip install .
```
4. Build the Ref app
```
cd <path/to>/fprime/Ref
fprime-util generate
fprime-util build
```
## Instructions for testing

**Please open your browser console during testing and watch for errors.** On Chrome and Firefox, this is done by right-clicking the web page > Inspect > Console. Any error or warning should be reported.

## G1 - Connectivity

| ID | Steps | Expected result|
| --- | --- | --- |
| G1.1 | Start the F' GDS with the built Ref app by running the command ```fprime-gds``` in the fprime/Ref/ directory | A browser session launches and the green circle is displayed in the top right corner, indicating the GDS is connected to the running application |

## G2 - Commanding

| ID | Steps | Expected result|
| --- | --- | --- |
| G2.1 | In the **Commanding** tab, under _Mnemonic_, select `cmdDisp.CMD_NO_OP_STRING` |  |
| G2.2 | Fill the _arg1_ cell with an arbitrary string, such as "Test" | The _Command String_ text box shows `cmdDisp.CMD_NO_OP_STRING <string>` |
| G2.3 | Click "Send Command" | A command is sent and displayed at the bottom of the page, with the same mnemonic and argument as was entered |

## G3 - Events
| ID | Steps | Expected result|
| --- | --- | --- |
| G3.1 | Navigate to the **Events** tab | Events are listed, confirming that the `cmdDisp.CMD_NO_OP_STRING` was dispatched, received, and completed. |

## G4 - Channels
| ID | Steps | Expected result|
| --- | --- | --- |
| G4.1 | Navigate to the **Channels** tab | Channels are listed and updated every second |
| G4.2 | In the Filters box, enter the value `cmdDisp` | The `cmdDisp.CommandsDispatched` channel shows the value `1` (or the number of commands you ran in G2) |

## G5 - Uplink
**Prerequisite:** create a test file to be uplinked. This file will be re-used in later tests.
``` 
echo "Test file" > ~/gds-test.txt
```
| ID | Steps | Expected result|
| --- | --- | --- |
| G5.1 | Navigate to the **Uplink** tab | Uplink tab is displayed |
| G5.2 | Click the _Upload_ button and upload the `gds-test.txt` file | The file is listed in the table below, State is `NOT STARTED` |
| G5.3 | Fill in `/tmp` in Destination Folder text box and click Uplink | Progress is 100%, State is `FINISHED` and destination is /tmp/gds-test.txt|
| G5.4 | Verify that the file was uplinked to your (own) machine: `cat /tmp/gds-test.txt` | The content of the file is printed |

## G6 - Downlink
| ID | Steps | Expected result|
| --- | --- | --- |
| G6.1 | Navigate to the **Commanding** tab |  |
| G6.2 | Set sourceFileName to `/tmp/gds-test.txt`, destFileName to `downlink-test.txt`, and click _Send Command_ | Command is sent |
| G6.3 | Navigate to **Downlink** tab | Downlink progress and confirmation can be seen |
| G6.4 | Verify that the file was downlinked to your (own) machine: `cat /tmp/fprime-downlink/downlink-test.txt` | The content of the file is printed |

## G7 - Charts
| ID | Steps | Expected result|
| --- | --- | --- |
| G7.1 | Navigate to the **Charts** tab|  |
| G7.2 | Click _Add Chart_ and select `blockDrv.BD_Cycles` | `blockDrv.BD_Cycles` is plotted and grows linearly |
| G7.3 | Click the pause button | Live plotting is paused |

## G8 - Command Sequencer

| ID | Steps | Expected result|
| --- | --- | --- |
| G8.1 | Navigate to the **Sequences** tab | |
| G8.2 | Paste in the sequence given below, name it `testSequence.seq` and click upload | Event tab shows the uplink is successful |
| G8.3 | Navigate to the **Commanding** tab and run the following command: `cmdSeq.CS_RUN /seq/testSequence.bin BLOCK` | Event tab shows all 3 commands were dispatched and executed successfully |

Sequence file:
```
R00:00:01 cmdDisp.CMD_NO_OP;
R00:00:02 fileDownlink.SendFile "/tmp/gds-test.txt" "/tmp/sequence-test.txt";
R00:00:03 cmdDisp.CMD_NO_OP_STRING "Test";
```

## G9 - Miscellaneous 
| ID | Steps | Expected result|
| --- | --- | --- |
| G9.1 | Open the **Dictionaries** tab and verify that the values are displayed properly and the filter is functioning | No anomalies |
| G9.2 | Open the **Logs** tab and verify that the events, commands and channels are logging | No anomalies |
| G9.3 | Open the **Advanced** tab and verify that the values are displayed properly | No anomalies |