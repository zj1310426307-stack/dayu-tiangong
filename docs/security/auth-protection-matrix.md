# Auth Protection Matrix

`401` means no valid trusted principal; `403` means authenticated but not permitted. Frontend button state is only user guidance—the backend is the security boundary.

| Endpoint / action | Anonymous | Viewer | Engineer | Reviewer | Freezer | Security Admin |
|---|---:|---:|---:|---:|---:|---:|
| Public health, GIS tiles/read | allow | allow | allow | allow | allow | allow |
| Read Dataset Version | allow | allow | allow | allow | allow | allow |
| `/auth/me` | 401 | allow | allow | allow | allow | allow |
| Import Preview / Commit | 401 | 403 | allow | 403 | 403 | 403 |
| Run hydraulic QA | 401 | 403 | allow | 403 | 403 | 403 |
| Edit / delete Dataset content | 401 | 403 | allow | 403 | 403 | 403 |
| Clone Dataset | 401 | 403 | allow | 403 | 403 | 403 |
| Submit Dataset review | 401 | 403 | allow | 403 | 403 | 403 |
| Review / Approve | 401 | 403 | 403 | allow | 403 | 403 |
| Freeze | 401 | 403 | 403 | 403 | allow | 403 |
| Publish / Retire | 401 | 403 | 403 | 403 | allow | 403 |
| Grant / revoke role | 401 | 403 | 403 | 403 | 403 | allow |

The legacy public Dataset read endpoints remain public for the current compatibility boundary. A later deployment may make reads authenticated without changing mutation authorization.
