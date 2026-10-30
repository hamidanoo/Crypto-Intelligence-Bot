# Roles and Permissions (Phase 8)

Permissions are granular and enforced at the API layer
through the `require_permission` dependency. Frontend
navigation hides items the user lacks, but that is
presentation only and is never security enforcement.
Authorization failures are audited.

## Permission list

dashboard.view, users.view, users.manage, roles.view,
roles.manage, audit.view, integrations.view,
integrations.manage, telegram.view, telegram.manage,
notifications.view, notifications.manage, settings.view,
settings.manage, scheduler.view, scheduler.manage,
scheduler.trigger, collections.run, announcements.view,
announcements.manage, intelligence.view,
intelligence.manage, competitions.view,
competitions.manage, volume.view, volume.manage,
market.view, market.manage, news.view, news.manage,
news_sources.view, news_sources.manage.

## Role matrix

| Permission | Super Admin | Admin | Operator | Viewer |
|---|:-:|:-:|:-:|:-:|
| dashboard.view | yes | yes | yes | yes |
| users.view | yes | yes | no | no |
| users.manage | yes | no | no | no |
| roles.view | yes | yes | no | no |
| roles.manage | yes | no | no | no |
| audit.view | yes | yes | no | no |
| integrations.view | yes | yes | no | yes |
| integrations.manage | yes | no | no | no |
| telegram.view | yes | yes | yes | yes |
| telegram.manage | yes | yes | no | no |
| notifications.view | yes | yes | yes | yes |
| notifications.manage | yes | yes | yes | no |
| settings.view | yes | yes | no | no |
| settings.manage | yes | no | no | no |
| scheduler.view | yes | yes | yes | yes |
| scheduler.manage | yes | yes | no | no |
| scheduler.trigger | yes | yes | no | no |
| collections.run | yes | yes | yes | no |
| announcements.view | yes | yes | yes | yes |
| announcements.manage | yes | yes | no | no |
| intelligence.view | yes | yes | yes | yes |
| intelligence.manage | yes | yes | no | no |
| competitions.view | yes | yes | yes | yes |
| competitions.manage | yes | yes | no | no |
| volume.view | yes | yes | yes | yes |
| volume.manage | yes | yes | no | no |
| market.view | yes | yes | yes | yes |
| market.manage | yes | yes | no | no |
| news.view | yes | yes | yes | yes |
| news.manage | yes | yes | no | no |
| news_sources.view | yes | yes | no | no |
| news_sources.manage | yes | yes | no | no |

Super Admin holds every permission. Admin holds all
operational permissions but cannot manage users, roles,
integrations, or security settings. Operator can view
operational data, run permitted collections, and manage
permitted notifications, but cannot manage users, roles,
credentials, or security settings. Viewer is read-only.

## Privilege-escalation guards

- A caller cannot grant a role or permission they do
  not themselves possess; the attempt is rejected
  with 403.
- A user cannot change their own role.
- A user cannot deactivate themselves.
- The last active Super Admin cannot be demoted or
  deactivated; the attempt is rejected. A second Super
  Admin must exist first, and the demotion must then be
  performed by another administrator.
- Role and permission changes are recorded in the
  audit log.

## Protected manual collection endpoints

Every manual collection endpoint now requires the
`collections.run` permission plus a valid CSRF token.
Unauthenticated requests get 401; authenticated users
without the permission get 403:

- `POST /announcements/collect`
- `POST /announcements/sources/{id}/collect`
- `POST /binance/collect/market`
- `POST /binance/collect/futures`
- `POST /alpha/collect`
- `POST /airdrops/collect`
- `POST /prime-sales/collect`
- `POST /competitions/collect`
- `POST /competition-volume/collect`
- `POST /competition-volume/{id}/collect`
- `POST /market/collect`
- `POST /futures/collect`
- `POST /news/collect`

Also protected: `PATCH /announcements/sources/{id}`
(announcements.manage), `POST/DELETE
/market/watchlist/{id}` (market.manage), all
`/admin/*` endpoints (per the matrix above), and all
scheduler controls (scheduler.manage for pause/resume,
scheduler.trigger for trigger).

Deliberately public (no data access, no mutation):
`POST /prime-sales/estimate-allocation` is a pure
calculation from caller-supplied inputs; it reads no
stored data and changes nothing, so it remains public.
Public market-data read endpoints also remain public.
