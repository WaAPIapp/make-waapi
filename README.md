# make-waapi

The WaAPI app for [Make](https://www.make.com), as local source.

`src/` is a Make Apps SDK project in the layout the official
[VS Code extension](https://github.com/integromat/vscode-apps-sdk) clones and
deploys: `makecomapp.json` lists every component and points at its code files.

## Status

**Nothing is published.** No Make account is connected yet, and `origins[0].appId`
in `src/makecomapp.json` still carries a `-FILL-ME-` placeholder.

## Why the surface is small

Make's own documentation:

> Once the app is published, it is not possible to delete the app or make it
> private again
>
> Once the app is published, it is not possible to delete any module or
> component

A module shipped once is permanent — it can be hidden or relabelled
`[DO NOT USE]`, not removed. So the app ships **7 modules**: three instant
triggers, three actions, and one universal module that reaches the remaining
119 client actions without turning them into 119 permanent components. A
universal module is a review prerequisite anyway. Whapi.Cloud's listed app
gets by with the same count.

The three triggers and three actions mirror the already-built Zapier app
(`../zapier-waapi/`) one for one. Those choices were made in
`eazewhatsapp-proxy/docs/superpowers/specs/2026-08-10-webhook-subscriptions-and-zapier-design.md`
and are not re-litigated here.

## Layout

```
src/
  makecomapp.json          the component index — every file below is referenced from here
  README.md                shown to users on the app's Make page
  general/base.iml.json    base URL, auth header, error mapping
  general/common.json
  modules/groups.json      how the modules are grouped in the scenario editor
  connections/waapi/       API-token connection
  rpcs/list-instances/     feeds the instance dropdown in every module
  webhooks/                attach/detach per event set — one subscription per scenario
  modules/                 3 instant triggers, 3 actions, 1 universal
```

## Deploying, once an account exists

1. Create the app in Make, note its app ID.
2. Put the Make API token in `.secrets/apikey` (gitignored). It needs the
   `sdk-apps:read` and `sdk-apps:write` scopes.
3. Fill `origins[0].appId` in `src/makecomapp.json`, and check `baseUrl`
   matches your Make zone (`eu1`, `eu2`, `us1`, …).
4. Open the workspace in VS Code with the Make Apps SDK extension, right-click
   `makecomapp.json` → **Deploy to Make**.

Deploying is not publishing. The app stays private until it is explicitly
published, and that is the irreversible step.

## Verified against the API, not assumed

- `GET /instances` returns `{ instances: [...] }` — the RPC iterates
  `body.instances`, not `body.data`.
- `POST /instances/{id}/webhooks` takes `{ url, events, source }` and `source`
  already accepts `make` as a value; the backend was built for this.
- The base response check treats `body.status == "error"` as a failure even on
  HTTP 200, which is how the API reports an instance that has dropped off.

## Verified in Make

Deployed to `waapi-3idhbi` on eu1 and exercised through the UI:

- The connection is accepted and the instance dropdown fills from
  `rpc://listInstances`.
- `attach` registers a subscription carrying the right events and
  `source: "make"`, and `detach` removes it when the webhook is deleted.
- An instant trigger fires on a real incoming message.
- The three send actions deliver; the universal module reaches an action with
  no dedicated module.
- A send against a disconnected instance answers HTTP 409 with
  `status: "error"` — the deliberate error scenario Make's review asks for.

Three defects the platform found that the API-level tests could not:

1. Make's base is inherited by **modules and RPCs only**. The connection and
   all six webhook files resolved `/instances` relative to nothing and failed
   with "Invalid URL" before any request went out.
2. `detach` built its path from two saved values; an empty half produced
   `.../instances//webhooks/9`, a 404 Make discards silently, leaving the
   subscription alive. `attach` now saves the finished URL.
3. The app had no icon, so the scenario editor showed a placeholder.

## Webhook lifecycle, as Make actually behaves

Worth knowing before changing anything here:

- A webhook is an object of its own. Switching a scenario off, trashing it,
  or deleting the trigger module does **not** remove it — only deleting it
  under **Webhooks** does, and that is what calls `detach`.
- `attach` runs when the scenario first runs, not when the webhook is created.
- A webhook's parameters cannot be changed afterwards. Pointing a trigger at a
  different instance means deleting the webhook and creating a new one, so the
  undocumented `update` directive is never reached and the app defines none.
