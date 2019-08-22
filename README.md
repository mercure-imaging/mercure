# Hermes DICOM Router

A flexible DICOM routing solution based on DCMTK toolkit. It consists of multiple separate modules / 
applications that handle different steps of the routing procedure.

Installation instructions and usage information can be found on the project homepage:
https://hermes-router.github.io

## Receiver
The receiver listens on a tcp port for incoming DICOM files. Received files are run through
a preprocessing procedure during which DICOM tag information is extracted and stored in a json
file.

## Router
The router module runs periodically and checks 
* if the transfer of a DICOM series has finished (based on timeouts)
* if a routing rule applies

If both conditions are true, the DICOM series is copied into separate outgoing folders
for each target. If no rule applies, the DICOM series is placed in the `discard` folder.

## Dispatcher
The dispatcher module runs periodically and checks
* if a transfer from the router has finished
* if the series is not already being processed
* if at least one DICOM file is available

If the conditions are true, the information about the DICOM target node is read from the 
`target.json` file and the images are sent the this node. After the transfer, the files
are moved to either the `success` or `error` folder.

## Cleaner
The cleaner module runs periodically and checks
* if new series arrived in the `discard` or `success` folder
* if the move operation into these folder has finished
* if the predefined clean-up delay has elapsed (typically 7 days)

If these conditions are true, series in the `success` and `discard` folders are deleted.

## Webgui
The webgui module provides a user-friendly web-based interface for configuring, controlling, and 
monitoring the DICOM route solution.
