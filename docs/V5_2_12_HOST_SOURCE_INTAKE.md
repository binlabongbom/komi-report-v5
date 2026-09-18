# Host source intake — 18 September 2026

## Latest user boundary: retain the existing Host

The user explicitly excluded Host code changes from version 5.2.12, rather than
merely postponing them until later in this release.
Do not modify/deploy its backend, schema, APIs, configuration, certificates or
data. This intake remains a read-only review of the existing implementation.
Desktop adapters may target a verified existing contract; if a capability needs
a Host change, exclude that change from this version and record the affected
feature limitation honestly, then continue independent Desktop
work. Missing backend evidence does not prove that the existing Host lacks the
capability and does not authorize inventing membership or bypassing trust.

Reviewed the two files supplied by the user without executing them, opening the
License screen, or calling Host APIs. This is a static frontend review, not a
backend or deployed integration test. No production data was changed.

| Supplied file | Bytes | SHA-256 |
| --- | ---: | --- |
| `screens-license.jsx` | 110183 | `ae14c41f23077257d7ee41eef7ccc45235c9cd65f8b2ca89cd20a52c1cd370eb` |
| `screens-license.js` | 83049 | `1ee10b454224ad3f55c08e107a4fc9c409b34b92fd742aa2327e4e5270f8b1bc` |

The JSX contains React screens for Proofreader and KOMI Report. The JavaScript
is minified browser code with the same discovered KOMI action names; this check
does not prove an exact build match. Neither file implements the PHP handlers.
Comments describe intended server behavior, but are not evidence that the
server validates requests that way.

## Observed integration surface

Line references below refer to the supplied JSX.

| Action on `/api.php` | Observed frontend use |
| --- | --- |
| `komi_overview`, `komi_installations` | Overview and installation list (817–818) |
| `komi_installation` | Detail by installation ID (1019) |
| `komi_set_status` | POST installation ID, status and reason (1316) |
| `komi_delete_installation` | POST installation ID (840) |
| `komi_companies` | Company choices for alert rules (1559) |
| `komi_license_issue` | POST signed request text and validity dates; response used as a downloadable offline license (1141) |
| `komi_alerts_run` | Run alerts on screen open/environment change, or manually (829, 1591) |

`company_key` appears in alert-rule company selections. The frontend receives
`company_key`, `company_name` and `installations` from `komi_companies`; its
comment describes grouping different company spellings. The implementation of
that grouping is absent. It must not be treated as authoritative company
membership or as permission to exchange LAN settings/history.

The screen keeps installation details keyed by `installation_id`. These files
alone do not establish why the user's two PCs appeared under one name, whether
their installation identities collided, or whether their settings were shared.

The supplied frontend exposes no peer membership verifier, signed membership
response, company-wide three-slot enforcement, or trusted registration-recovery
configuration. This does not establish that those capabilities are absent from
the Host backend. The Proofreader signing comments concern a separate product
and are not a KOMI peer trust specification.

## Concrete backend files needed next

Request the following source, or repository paths, without production secrets:

1. `register-api.php`, named by this screen as the Desktop registration API,
   plus its included registration/authentication implementation files.
2. The `/api.php` router and actual handlers for `komi_companies`,
   `komi_installation`, `komi_set_status`, and `komi_license_issue`.
3. Schema/migrations and supporting code those handlers use to bind companies,
   installations, public keys/tokens, and printer slots. If verified LAN
   membership already has a separate handler, include that implementation.

Inspect these before deciding whether to adapt an existing API or propose a
new one. Browser administrator credentials are not Desktop peer credentials.
No private keys, customer database dump, or additional login is needed for this
source review.

Read-only repository lookup on 18 September also found no PHP backend in the
local Desktop tree. The connected account lists seven repositories; none is
named for DMSKM or the Host. The complete, non-truncated Git trees of the two
plausible generic web repositories (`Projects` at
`6f70bda56c0cf02e60b59f45eeb2773c94da3f89` and `km-it-promotion` at
`261a5a520c2148c29629d652dcfab9d24f7d77bd`) have no PHP, `register-api`,
`screens-license` or DMSKM paths. Several repositories are not search-indexed:
an empty code-search result is not evidence that the backend does not exist.
No repository or Host data was changed during this lookup.

## Findings to check with the Host implementation

- The environment helper adds `env=staging` to `komiApi` calls (749–755), but
  offline issuance calls `/api.php?action=komi_license_issue` directly (1141).
  Therefore that request does not carry the selected staging environment.
  Backend routing is needed to establish the effect; do not test issuance on
  production. When fixing this, verify both the issuance namespace and license
  signing policy, rather than assuming that adding a parameter is sufficient.
- Opening the KOMI tab or changing its environment executes a POST to
  `komi_alerts_run` (829), which can send notification emails according to the
  screen's code/comments. Loading this screen is consequently not guaranteed
  to be read-only. Review through source until the backend behavior is known.
- Alert rules use `dbLoad('komi_alerts')` / `dbSave('komi_alerts', ...)`, whose
  definitions are not supplied. Their environment isolation cannot be verified
  from these files.

The attachments were not copied over Desktop source or modified. Production
membership integration remains pending backend evidence; existing isolated
repositories and source simulations remain valid within their stated scope.
