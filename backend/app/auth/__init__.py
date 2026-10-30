"""Administrator authentication, authorisation, and credential security.

Sessions are server-side only. The browser holds an opaque
session token in an HttpOnly cookie; the token hash is what
is stored. Permissions are granular and enforced at the API
layer; frontend visibility is never treated as enforcement.
"""
