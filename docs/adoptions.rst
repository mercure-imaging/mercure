Notable Adoptions
=================

mercure has been adopted by research groups and institutions beyond the original development team at NYU Langone Health / CAI2R. This page documents known deployments and integrations in the community.

If your institution uses mercure and you would like to be listed here, please submit a pull request or open an issue on our `GitHub repository <https://github.com/mercure-imaging/mercure>`_.


BIDS-flux (Multi-site Neuroimaging)
-----------------------------------

`BIDS-flux <https://bids-flux-docs.readthedocs.io/>`_ is a scalable data management platform for multi-site neuroimaging research, built on FAIR principles (Findability, Accessibility, Interoperability, Reusability).

**Institutions involved:**

* CHU Sainte-Justine (Montreal)
* University of Catalonia (Universitat Oberta de Catalunya)
* SickKids - The Hospital for Sick Children (Toronto)

**How mercure is used:**

In the BIDS-flux architecture, mercure serves as the **data ingestion and curation component** at each local research site. It handles incoming DICOM data from MRI scanners before the data flows through the rest of the pipeline:

.. code-block:: text

   Mercure (ingestion) → Heudiconv (DICOM-to-BIDS) → Standardization →
   Anonymization → Quality control (MRIQC) → Processing (BIDSApps)

The platform operates on a distributed model where mercure runs as part of the local infrastructure at individual sites, enabling independent data contribution to a centralized repository. This makes mercure essential for their distributed multi-site data collection model.

**Notable project:** The Canadian Paediatric Imaging Platform (C-PIP), a three-year longitudinal study involving approximately 750 pediatric participants undergoing annual MRI scans and neuropsychological assessments.

**More information:** https://bids-flux-docs.readthedocs.io/
