
![Python application](https://github.com/mercure-imaging/mercure/workflows/Python%20application/badge.svg) ![GitHub](https://img.shields.io/github/license/mercure-imaging/mercure) [![Join the chat at https://gitter.im/mercure-imaging/Support](https://badges.gitter.im/mercure-imaging/Support.svg)](https://gitter.im/mercure-imaging/Support?utm_source=badge&utm_medium=badge&utm_campaign=pr-badge&utm_content=badge)


![mercure](mercure.png)

| **Note:** mercure (formerly called Hermes) is still undergoing development work. While now feature-complete for the release of version 0.2.0, we are still testing and improving the code. Use at your own risk.  |
| :--- |

# mercure DICOM Orchestrator

A flexible DICOM routing and processing solution with user-friendly web interface and extensive monitoring functions. Custom processing modules can be implemented as Docker containers. mercure has been written in the Python language and uses the DCMTK toolkit for the underlying DICOM communication. It can be deployed either as containerized single-server installation using Docker Compose, or as scalable cluster installation using Nomad. mercure consists of multiple service modules that handle different steps of the processing pipeline.

Installation instructions and usage information can be found in the project documentation:  
https://mercure-imaging.org/docs/index.html


## Receiver
The receiver listens on a tcp port for incoming DICOM files. Received files are run through
a preprocessing procedure, which extracts DICOM tag information and stores it in a json file.

## Router
The router module runs periodically and checks 
* if the transfer of a DICOM series has finished (based on timeouts)
* if a routing rule triggers for the received series (or study)

If both conditions are met, the DICOM series (or study) is moved into a subdirectory of the `outgoing` folder or 
`processing` folder (depending on the triggered rule), together with task file that describes the action to be performed. 
If no rule applies, the DICOM series is placed in the `discard` folder.

## Processor
The processor module runs periodically and checks for tasks submitted to the `processing` folder. It then locks the task and executes processing modules as defined in the `task.json` file. The requested processing module is started as Docker container, either on the same server or on a separate processing node (for Nomad installations). If results should be dispatched, the processed files are moved into a subfolder of the `outgoing` folder.

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
The webgui module provides a user-friendly web interface for configuring, controlling, and 
monitoring the server.

## Bookkeeper
The bookkeeper module acts as central monitoring instance for all mercure services. The individual modules communicate with the bookkeeper via a TCP/IP connection. The submitted information is stored in a Postgres database.
