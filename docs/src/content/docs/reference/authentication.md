---
title: Authentication
template: doc
---

### Authentication Basics

> Get authentication token:

```bash
curl -X POST -d "username=testuser&password=testpass" http://localhost:8000/api/token-auth/

{"token":"eyJ0eXAiO..."}
```

> Use authentication token:

```bash
curl -H "Authorization: JWT <your_token>" http://localhost:8000/api/projects/

{"count":13, ...}
```

> Use authentication token via querystring (less secure):

```bash
curl http://localhost:8000/api/projects/?jwt=<your_token>

{"count":13, ...}
```


`POST /api/token-auth/`

Field | Type | Description
----- | ---- | -----------
username | string | Username
password | string | Password

To access the API, you need to provide a valid username and password. You can create users from WebODM's Administration page.

If authentication is successful, you will be issued a token. All API calls should include the following header:

Header |
------ |
Authorization: JWT `your_token` |

The token expires after a set amount of time. See [Token Expiration](#token-expiration) for more information.

Since applications sometimes do not allow headers to be modified, you can also authenticate by appending the `jwt` querystring parameter to a protected URL. This is less secure, so pass the token via header if possible.


### Token Expiration

The token expires after six hours by default. The expiration time is defined in the settings module of Django in WebODM. If building WebODM from sources or running it natively, the expiration time can be changed in the `JWT_AUTH['JWT_EXPIRATION_DELTA']` variable. Otherwise, e.g. using the docker images, you will have to request another token when a token expires.

You know that a token has expired if any API call returns a `403` status code with the JSON body `{'detail': 'Signature has expired.'}`.

### External identity migration

External authentication now stores a separate mapping from the configured
`EXTERNAL_AUTH_ENDPOINT` and provider `user_id` to a local account. Provider IDs
are positive integers and do not determine local database IDs. New accounts have
unusable local passwords and no staff or superuser status. External login and
session restoration reject inactive, staff, and superuser accounts.

Apply database migration `0048_external_identity` before running the new code.
The migration intentionally does not infer links from existing usernames or IDs:
legacy accounts have no reliable provenance marker. Before restoring external
login for an existing account, verify its provider identity and local ownership,
then run these commands with the production external endpoint configured:

```bash
python manage.py linkexternaluser --external-id 100 --user existing-user --dry-run
python manage.py linkexternaluser --external-id 100 --user existing-user
```

Linking keeps the existing local primary key, projects, quotas, and permissions.
Review those permissions before linking; this command explicitly grants the
external identity access to that local account. It refuses inactive, staff, or
superuser accounts and conflicting mappings. Matching a local username without
an explicit link denies login, even if its numeric ID also matches.

The provider namespace is a hash of the exact configured endpoint. Changing that
endpoint prevents old mappings and external sessions from being used; review and
migrate mappings explicitly rather than automatically trusting a new provider.
Cluster account exports do not include these mappings: establish a verified link
on the destination after importing the local account.

Existing external-backend sessions without a mapping require login again.
Before deployment, invalidate legacy sessions and outstanding JWTs that may have
been issued through the vulnerable flow, including token logins previously
recorded with the local backend. New external token logins use the external
backend so session restoration checks the mapping and account status.
