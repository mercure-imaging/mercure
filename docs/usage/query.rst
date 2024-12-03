Query Tool
==========

Mercure Query enables pulling series and studies from various servers. It is an alternative to the "push" workflows that the Mercure receiver enables. 

.. image:: /images/ui/query.png
   :width: 550px
   :align: center
   :class: border

To query a node, you must have at least one target with type set to "Pull" or "Both." Other targets will not appear in the dropdown list. 

A query requires one or more accession numbers to start with, separated by commas. Mercure will attempt to query every study that has that one of the listed accessions. Unless otherwise specified, Mercure will pull every dicom from every series attached to those studies.

The **Upload List** button lets you pick a text file from your computer to use as a source of accession numbers, either comma or newline separated. 

Filtering by Study Description
------------------------------
The "Study Descriptions" entry can be a comma-delimited list of exact ``StudyDescription`` s which will be used to filter the query results. Mercure will retrieve any studies (with the given accession numbers) that match any of the given Study Descriptions

Filtering by Series Description
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Similarly, the "Study Descriptions" entry can be a comma-delimited list of exact ``SeriesDescription`` s, and again Mercure will retrieve only the series that correspond to one of these. 

The "Mercure" destination
-------------------------

By default, the tool sends retrieved dicoms back into Mercure to be processed by whichever rules are configured. 

Setting "Force Rule" will tell Mercure to ignore the rule criteria and force Mercure to treat these DICOMs as if they had only triggered the given rule. Even if these DICOMs would not have triggered this rule, and even if other rules would have triggered, only the "Force Rule" rule will run.

Other destinations
-------------------

The Query tool only sending dicoms directly to folder targets, but for others you will need to send the case to Mercure and set up a rule to handle them.

Off-peak processing
-------------------

Setting the off-peak slider will restrict queries from running during peak hours. It will automatically pause a running query when peak hours begin, and continue when peak hours end. 