# ios-parity: everything the web app does with a server, in the iPhone app (orchestrator note)

Status: in progress (2026-11-26)

Owner, 2026-11-26: "for the ios id like to be able to do anyting that can be done on the web app with a sever to be available
in the ios app without the need for a server if the setting makes since without a server". Also: care team notes on the phone
(yes), Withings and Whoop set up from the phone (yes), Profile weight in lb (yes).

## Work, one helper role each (each keeps its own docs/dev/progress/<role>.md)
* profile-weight-units: Profile weight boxes follow user.units.weight.
* phone-reminders: Reminders as the iPhone's own local notifications, no server needed.
* phone-care: care team notes and suggestions on the phone through the paired server.
* phone-devices: Withings and Whoop from the phone, with a server and without one.
* phone-ai-more: AI order, swaps and day plans on the phone.
* phone-recipe-import: recipe import from a web page with no server.

## Left out on purpose (need a server by nature)
Admin, accounts (password, two-step, passkeys, sign-in), phone shortcut tokens, outside AI apps (MCP), sharing with a care team
when there is no server (nobody to share with).
