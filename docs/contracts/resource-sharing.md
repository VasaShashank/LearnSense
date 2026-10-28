# Resource and class-material sharing contract

## Globally shared educational resources

- `POST /api/resources` creates or replaces a record in the shared educational-resource catalog.
- The request requires a verified Supabase bearer token and an active `TEACHER` or `ADMIN` membership in at least one organization.
- A caller-supplied user ID or role is ignored; authorization uses the verified token identity and server-side membership.
- `GET /api/resources/{resource_id}` remains public for existing educational-resource reads. No update or delete route currently exists; POST is the only HTTP mutation route.

## Private uploaded class materials

- Uploads remain private to their verified uploader by default. Ownerless legacy uploads stay inaccessible.
- An assigned active organization teacher who owns the document can grant their document to a class with `POST /api/classes/{class_id}/materials/{document_id}/share`.
- The class and organization are resolved server-side from `class_id`; no caller-supplied organization or owner ID grants access.
- The class grant is persisted at `storage/document_shares/{document_id}.json`. It records the document, class, owner, sharing user, and creation time. Repeating the grant is safe.
- A learner can read a granted document only while the grant exists and the learner has trusted Supabase provisioning, an active `LEARNER` membership in that class's organization, and an enrollment in that class.
- The uploader retains access. Other users and other classes remain denied.
- The verified uploader can revoke their grant with `DELETE /api/classes/{class_id}/materials/{document_id}/share`, including after class assignment changes. Repeated revocation is safe. Revocation does not remove the uploader's access.
- Class grants enable reads of document metadata/content/pages/assets, source listings, and processing status. They do not permit cancellation; document and source-job cancellation remain uploader-only.

The grant repository uses the existing local JSON persistence pattern and atomic file replacement. No PostgreSQL migration is required for this prototype. The grant files must be kept on the same persistent storage volume as document ownership and upload data; multi-instance filesystem coordination is not implemented.
