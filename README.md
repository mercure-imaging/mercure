![mercure](mercure.png)

# mercure DICOM Router

A flexible DICOM routing and processing solution using a Python application layer on top of the DCMTK toolkit. It consists of multiple separated modules that handle different steps of the processing chain.

**Important:** mercure (formerly called Hermes) is currently undergoing significant development work towards version 0.2. Make sure to checkout the branch *stable-v0.1* for a stable version.

Installation instructions and usage information (for the stable 0.1 version) can be found on the project homepage:
https://hermes-router.github.io


## Receiver
The receiver listens on a tcp port for incoming DICOM files. Received files are run through
a preprocessing procedure during which DICOM tag information is extracted and stored in a json
file.

## Router
The router module runs periodically and checks 
* if the transfer of a DICOM series has finished (based on timeouts)
* if a routing rule is triggered for the received series

If both conditions are true, the DICOM series is copied into separate outgoing folders
for each target. If no rule applies, the DICOM series is placed in the `discard` folder.

## Processor
The processor module runs periodically and checks for tasks submitted in the processing folder. It then locks the task and executes processing modules, as defined in the task.json file.

## Dispatcher
The dispatcher module runs periodically and checks
* if a transfer from the router or processor has finished
* if the series is not already being dispatched
* if at least one DICOM file is available

If the conditions are true, the information about the DICOM target node is read from the 
`task.json` file and the images are sent to this node. After the transfer, the files
are moved to either the `success` or `error` folder.

## Cleaner
The cleaner module runs periodically and checks
* if new series arrived in the `discard` or `success` folder
* if the move operation into these folder has finished
* if the predefined clean-up delay has elapsed (typically 5 days)

If these conditions are true, series in the `success` and `discard` folders are deleted.

## Webgui
The mercure webgui module provides a user-friendly web interface for configuring, controlling, and 
monitoring the server.

## Bookkeeper
The bookkeeper module acts as central monitoring instance for all mercure services. The individual modules communicate with the bookkeeper via a TCP/IP connection. The submitted information is stored in a Postgres database.

