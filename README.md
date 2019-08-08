# Hermes

A dicom proxy based on DCMTK. This proxy consists of several separate modules/
applications which handels different parts.


## Receiver/Server
The receiver listens on a tcp port for incoming messages. The file is run through
a extraction process where dicom tag information is extracted and stored in a json
file.

## Router
The router runs periodically and checks 
* is the transfer finished (based on timeouts)
* does a rule apply 

If both conditions are true, DICOM series are copied for each target to a separate
folder. If no rules have been applied the DICOM series is put into the 
`discard folder`.


## Dispatcher
The dispatcher runs periodically and checks
* copy from router is finished
* it is not currently already sending
* and some DICOMS are available

If the conditions are true, a `destination.json` is read and it starts sending. 
After sending it is moved to either the `success folder` or `error folder`.


## Cleaner
The cleaner also runs periodically and checks
* copy is finised
* some predefined time has elapsed

The those conditions are true data is deleted from the `success folder` and 
`discard folder`.
