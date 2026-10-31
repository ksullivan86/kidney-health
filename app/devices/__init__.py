"""Connected devices (design note 27; ARCHITECTURE "Connected devices"): the server signs in to a device company with the person's
consent and fetches only that person's own readings into their log. Nothing about the person is sent out.

* :mod:`app.devices.base`: what every provider offers (:class:`Provider`), the readings it hands back and :class:`ProviderError`.
* :mod:`app.devices.withings`: Withings (weight, blood pressure, pulse). Whoop (0.17) adds a module beside it.
* :mod:`app.devices.store`: the connections (tokens sealed with the app's keyring), the import ledger and adding readings to
  ``weights`` and ``blood_pressures`` without ever changing a row that is already there.
* :mod:`app.devices.sync`: one person's sync, and the loop that syncs everyone every ``devices.sync_hours``.
* :mod:`app.devices.api`: ``/api/devices``: list, connect (the way out and back), sync now, disconnect.
"""
