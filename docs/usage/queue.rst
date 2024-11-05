Queue management
================

The "Queue" page allows monitoring the status of mercure's processing and routing queues, and it provides basic functions for modifying jobs in the processing queue.

.. image:: /images/ui/queue.png
   :width: 550px
   :align: center
   :class: border

.. note:: By default, the views do not update automatically when the page is open, as this could have negative impact on the server load. Press the Refresh button in the top-right corner to update the queue lists. When pressing the Auto Update button, the view will be updated every 10 sec.

Queue status
------------

The upper part of the page indicates if mercure is currently processing or routing images. Using the switches "Suspend Queue", you can halt the processing or routing queue. In this case, mercure will finish the active job but will not start another job until the queue has been started again. This can be helpful if it is necessary to patch job parameters, or if module settings need to be changed before additional series can be processed.

Job status
----------

The lower part of the page shows the status of individual jobs in mercure's different queues. 

.. important:: Some of the functions for modifying jobs are still incomplete and will be added in future versions of mercure.
 
The "Processing" tab shows the jobs currently placed in the processing queue, i.e. jobs (series or studies) for which processing modules are executed. You can mark jobs by clicking on the corresponding row. This will activate the toolbar above the table, which allows, e.g., displaying additional job information or deleting jobs. Similarly, the "Routing" tab shows the outgoing jobs currently placed in the routing queue.

.. image:: /images/ui/queue_processing.png
   :width: 550px
   :align: center
   :class: border

The "Studies" tab show the list of studies currently waiting for complete image arrival, i.e. studies for which a study-level rule has triggered and for which DICOM series are still being collected. It allows enforcing the completion of the series collection by clicking the button "Force study completion".

The "Failure" tab shows a list of all jobs for which processing errors have occurred, including errors during preparation, processing, and routing. Failed jobs can be restarted -- if possible depending on the error type.

The "Archive" tab shows a search box that allows reviewing the status of series/studies still residing on the server that have completed processing/routing or that have been discarded because no rule had triggered. Because there is typically a high number of such jobs, it has been implemented as search box instead of a table with all entries. In the future, it will be possible to reprocess such cases (e.g., if a series had not been processed because the selection rule was incorrect).

.. note:: If you send a DICOM series to mercure, it takes a short time before the series becomes visible on the Queue page (i.e. on the Processing, Routing, or Studies tab) because mercure first waits for expiration of the series completion timeout (60 sec by default).
