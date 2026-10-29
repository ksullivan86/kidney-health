# Symptoms log

**Today → Symptoms → Add** records a symptom, severity, date and optional note. **Other** lets a
person give the symptom a name. Each entry has **Edit** and **Delete**; deletion asks first.
Days after today cannot be recorded. Symptoms need the connection to the server and are not queued offline.

Changing the date clears the card before the new day's request starts. It shows **Loading symptoms…**
while waiting. A failed read offers **Try again**, and a late reply cannot restore another day's
entries or handbook blocks. Symptoms loads independently, even if the food log is delayed or fails.
A failed save keeps the entries in the form so the person can retry.

**Trends → Symptoms** groups entries by symptom, with the number of days, worst severity and dates.
Symptoms also appear in the person's data export and Visit prep. They are not sent to an AI provider.
The app records what the person entered; it does not interpret symptoms. Any warning-sign text comes
from the handbook.

See the [architecture contract](../ARCHITECTURE.md#symptoms-log-schema-step-15) for the data and API,
and [Reports for your care team](../handbook/docs/app/reports-for-your-team.md#symptoms-you-write-down)
for the screen's instructions.
