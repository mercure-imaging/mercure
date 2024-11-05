
Rules
--------------

After you have configured your targets and processing modules, you can define rules that specify which DICOM series should be processed and to which targets the images should be dispatched. This can be done on the "Rules" page.

.. image:: /images/ui/rules/rules.png
   :width: 550px
   :align: center
   :class: border

It is not necessary to stop mercure services while defining new rules. The mercure service modules will automatically reload the new configuration when a rule has been added or modified. Click the "Add New" button to create a new rule, or click on any of the existing rules and select "Edit" to modify it.

**Filtering tab**

All rules are evaluated whenever a new DICOM series has been received. The rules can use a set of DICOM tags extracted from the incoming DICOM files. To see the full list of DICOM tags available for writing rules, click the "Available Tags" button.

.. tip:: If you need additional tags that are currently not in the list, please contact us (or modify the getdcmtags module yourself).

When writing the selection rule, tags can be referenced using the format @TagName@, for example @PatientName@. When the rule gets evaluated, such tag placeholder will be replaced with the values read from the individual received DICOM series.

.. image:: /images/ui/rules/edit.png
   :width: 550px
   :align: center
   :class: border

A received series will processed if the selection rule evaluates to True, and it will be ignored if the rule evaluates to False. If none of the defined rules evaluates to True, the series will be discarded.

Selection rules can be written in a Python-like syntax. For example, the rule

.. highlight:: none

:: 

  'CINE' in @SeriesDescription@

will activate for all series that have the word "CINE" in the series description (e.g., "CINE 2ch"). If you only want to send series that are exactly called "CINE", use the following rule instead
:: 

  @SeriesDescription@ = 'CINE'

This rule would not trigger if the series is called "CINE 2ch". Multiple conditions can be combined using the "or" and "and" operators. Here, it is recommended to enclose every sub-condition with "( )". By default, DICOM tags are treated as strings and are case-sensitive. If you want to make your condition case-insensitive, then append ".lower()" to the tag. For example, the rule 
:: 

  @SeriesDescription@.lower() = 'cine'

would trigger for series called "CINE" or "cine". If you want to test for numerical value thresholds (e.g., if the slice thickness is lower than 2mm), you first need to convert the tag into a float by writing the tag inside "float( )". This then allows you to write a rule like
:: 

  float(@SliceThickness@) < 2.0

To test a selection rule before activating it, click the icon with the cog wheels on the left side of input box. If you see a red icon in the dialog, the rule notation is invalid (the dialog will tell you why). If the rule is valid, the dialog will test if the rule would trigger if a DICOM series with the values shown in the lower part of the dialog would be received. You can modify these values and test if the rule reacts as expected.

.. image:: /images/ui/rules/test.png
   :width: 550px
   :align: center
   :class: border

.. hint:: If you make a mistake while changing the test values (e.g., missing a quotation mark), you will see a yellow icon. 

If you have validated that your rule triggers as expected, select the desired Action from the drop-down list. The following options are available:

==================== ===============================================================================
Action               Meaning
==================== ===============================================================================
Routing              The received series/study will be dispatched to a target (no processing)
Processing & Routing The received series/study will be processed and afterwards dispatched
Processing only      The received series/study will be processed (without further dispatching)
Notification only    A notification will be triggered if the series/study is received (without neither processing or dispatching)
Force discard        The received series/study will be discarded (no other rules will be evaluated)
==================== ===============================================================================

Depending on the selected Action, the tabs "Processing" and "Routing" will become visible. 

The Trigger control allows selecting when the action should be triggered. If "Completed Series" has been selected, the action is executed when a DICOM series has been received for which the rule evaluates to True. Thus, if multiple series from a patient study are received, these series are processed separately. However, sometimes it is required to process all DICOM series from one patient study together. For example, an AI-based analysis algorithm might require multiple series with different contrast. In this case, the option "Completed Study" needs to be selected, and the additional control "Completion Criteria" will appear, which allows selecting when the study should considered complete. 

.. image:: /images/ui/rules/edit_trigger.png
   :width: 550px
   :align: center
   :class: border

If it is known which image series are required for the processing, this information can be utilized with the option "List Series Received". It is then necessary to list the Series Descriptions of the required series in the input box on the right side. Here, it is possible to enter substrings of the Series Description and it is possible to combine multiple options using the keywords "or" and "and". This allows handling variability in the Series Descriptions, which often occurs in practice due to inconsistent configuration of imaging devices. If the names of the expected series are unknown, the option "Timeout Reached" can be used, which collects image series belonging to the same study until no further series has been received for a definable timeout period (the timeout time can be set on the Configuration page). A disadvantage of this option is that the processing will be delayed until the timeout period has expired.

If the Priority control is set to "Urgent", corresponding series or studies will be pushed to the front of the processing queue, while the setting "Off-Peak" enforces that the corresponding series will be only processed at night time. The latter can be helpful to avoid that computationally demanding research studies might delay clinical routine processing during normal work hours.

Rules can be temporarily disabled by toggling the "Disable Rule" switch. In this case, the rule appears in grayed-out color in the rule list and it will be ignored during processing. By clicking the "Fallback Rule" switch, the current rule will be applied to all DICOM series for which no other rules have triggered. This allows defining a "default" rule.

**Processing tab**

For rules involving processing, the "Processing" tab can be used to select the processing module that should be executed and to provide rule-specific module settings. These settings will be merged with the global module settings and will overwrite global settings if the same keys occur in both settings. The settings have to be specified in JSON format. It depends on the individual module which settings are available. This information should be looked up from the module documentation. 

.. image:: /images/ui/rules/edit_processing.png
   :width: 550px
   :align: center
   :class: border

When selecting the "Retain input images" switch, the module will output both the processed images as well as the unprocessed input images. It depends on the individual application if this option is desired or not.

.. important:: The "Retain input images" option must not be used with modules that should remove confidential information from the data, such as DICOM anonymization modules.

**Routing tab**

For rules involving dispatching, the "Routing" tab can be used to select the target to which the DICOMs should be dispatched (after finishing processing modules, if selected). At this time, images can only be dispatched to a single target per rule. If images should be sent to multiple destinations, it is currently necessary to define multiple rules with different target. This limitation will be removed in future versions of mercure.

.. image:: /images/ui/rules/edit_routing.png
   :width: 550px
   :align: center
   :class: border

**Notification tab**

The "Notification" tab allows configuring webhook calls that are triggered when the rule gets activated, when the processing completes, and when an error occurs that is related to the rule. Webhook calls can be used to send notification messages into Slack, WebEx, Teams, or comparable messaging services. They can also be used for connecting other external services, for example, changing the color of a physical status light.

.. image:: /images/ui/rules/edit_notification.png
   :width: 550px
   :align: center
   :class: border

The URL and payload for the webhook call need to be provided. Payload templates for Slack and WebEx can be inserted by pressing the button "Insert Template". To obtain the webhook URL, you need to go into the configuration of your messaging service (e.g., Slack) and follow the instruction for setting up an incoming webhook.

.. important:: Do not send any sensitive information in the payload because the webhook call will, in most cases, be sent to an externally operated service.

**Information tab**

The "Information" tab can be used to document the rule. The purpose of the rule can be written as free-text into the Comment field, and an email address can be written into the Contact field, so that it can be looked up at a later time why the rule was defined and who requested it. It is also possible to add tag attributes to the rule. These tags are not yet used for anything else, but might be used in future versions of mercure for filtering purpose and access control.

.. image:: /images/ui/rules/edit_information.png
   :width: 550px
   :align: center
   :class: border


