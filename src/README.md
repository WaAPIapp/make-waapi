# WaAPI for Make

Send and receive messages from your Make scenarios through the
[WaAPI](https://waapi.app) REST API.

## Connect

1. Create an API token at **waapi.app → Settings → API Tokens**.
2. In Make, add a **WaAPI** connection and paste the token.

The token needs the **read** scope to list your instances and the **update**
scope so a scenario can subscribe to events when you switch it on and
unsubscribe when you switch it off. A token with read only will connect, but
every trigger will fail to start.

## Triggers

| Module | Fires when |
|---|---|
| Watch New Messages | the connected account receives a message |
| Watch Message Status | a message you sent is delivered or read |
| Watch Instance Status | the instance connects, disconnects, fails to authenticate, or shows a new QR code |

Each scenario gets its own subscription, so several scenarios can watch the
same instance without displacing one another.

## Actions

**Send a Message**, **Send Media** and **Send a Location** cover what most
scenarios need.

Everything else the API offers — groups, contacts, labels, polls, channels,
presence and the rest of the 122 client actions — runs through **Make an API
Call**. Point it at
`/instances/{id}/client/action/{action}` and pass the body the action expects.

## The chat ID is the one thing to get right

Its suffix decides where a message lands, and a wrong suffix is accepted and
delivers nothing:

| Target | Format |
|---|---|
| One person | `4915112345678@c.us` |
| Group | `123456789-123456789@g.us` |
| Channel | `123456789@newsletter` |

## Errors

A successful HTTP exchange is not proof a message was sent: the API answers
`200` with `{"status": "error"}` when the connected account has dropped off.
This app treats that as a failed module run rather than passing an
error-shaped bundle down the scenario.

## Support

Documentation: <https://waapi.app> · Issues: <https://waapi.app/contact>

WhatsApp is a trademark of WhatsApp LLC. WaAPI is an independent service and
is not affiliated with, endorsed by or sponsored by WhatsApp LLC or Meta
Platforms, Inc.
