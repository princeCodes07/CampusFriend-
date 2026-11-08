# Separate Cloudinary media preparation — 2026-11-08

**No upload, asset deletion, database media update, dependency installation or
storage configuration change has been performed. This is a separate approval.**

## Media audit

- Original catalog: 19 image references; 18 valid existing files.
- Original missing image: product 20 (`frame`), path
  `products/2026/09/3bfb5b281df09ec67c66e3a463714000.jpg`.
- Owner-selected catalog: product IDs 6–19, **14 references to 14 distinct valid
  files**, totaling **416,328 bytes**. All selected images are present.
- Product 20 was excluded from the export selection, not deleted locally. Its
  missing file remains an original backup-restoration issue.
- Dimensions, detected formats, byte sizes, SHA-256 hashes and original relative
  paths are recorded in the private media manifest. Original images are intact.
- A separate private backup of all 40 existing media files (4,065,694 bytes) was
  created and verified by SHA-256, including files outside the selected catalog.
- Repair images and unrelated files are outside this public product-media scope.

Current Product.image is a Django ImageField using FileSystemStorage. Production
does not serve uploaded media through Django's DEBUG-only media URL route.
Changing DATABASE_URL or running collectstatic will not move product photos.
Render's ephemeral disk is unsuitable for keeping these uploaded images across
restarts. [Render filesystem behavior](https://render.com/docs/free)

## Upload plan, after separate approval

1. Confirm the correct Cloudinary product environment and account owner. Keep
   CLOUDINARY_URL/API credentials in private environment settings on the approved
   upload machine and service. Do not place them in source, fixtures, logs or
   shell arguments. Confirm account limits and backup settings; do not assume
   the provider's backups replace the local originals.
2. Make a protected image backup. Re-hash each selected local file against the
   manifest immediately before upload; abort if content/path changed.
3. Upload from the owner's machine through the official Python SDK over HTTPS.
   Use signed server-side uploads, `resource_type="image"`, explicit stable
   public IDs, `overwrite=False`, `unique_filename=False`, and no incoming
   transformations. The planned public ID is
   `campusfriend/catalog-20261108/<full source SHA-256>` without a file extension.
   This identifies bytes independently of product names and supports safe reuse.
4. Include source SHA-256 in asset context. If the public ID already exists,
   verify its content/provenance before reusing it; an existing response is not
   proof it is the same image. Never retry with overwrite enabled. Signed upload
   defaults can overwrite, so explicitly set false.
   [Cloudinary upload options](https://cloudinary.com/documentation/image_upload_api_reference)
5. Record each returned asset_id, public_id, version, secure_url, format, bytes
   and dimensions beside the source product ID/path/hash. Verify the original
   asset download and expected properties before marking it complete. Retain the
   complete mapping privately and keep API secrets out of that mapping.
6. Resume only verified assets after partial failure. Do not delete a newly
   uploaded asset merely because a later upload failed. No database paths change
   during the upload stage. Expected approved asset count is 14, with zero
   replacements or deletions of existing Cloudinary assets.

The prepared `private/cloudinary-upload-plan.json` has these exact planned IDs
and source checksums; all `uploaded` flags are false and remote IDs/URLs are unset.

## Separate application integration

Use the official Cloudinary Python SDK and a new optional Cloudinary reference
on Product while retaining the existing ImageField and original path. This is
a proposed additive model migration, not part of the catalog importer. It avoids
destroying the local image reference during media cutover.
[Official Django integration](https://cloudinary.com/documentation/django_image_and_video_upload)

Before implementation, pin/test the chosen SDK version, design the optional
CloudinaryField/reference and secure URL helper, update templates/admin upload
handling, and test a feature flag that leaves local SQLite/FileSystemStorage
working. Do not merely set MEDIA_URL to a Cloudinary prefix or insert arbitrary
full URLs into the current ImageField and assume .url will behave correctly.

Suggested controlled order:

1. Upload/verify the 14 assets after media approval, leaving database rows alone.
2. In the approved maintenance window, complete and verify the catalog transfer
   against the current schema before changing the model schema.
3. Apply the separately reviewed additive media schema/code change, then set
   only Cloudinary references whose product PK and original image path still
   match the manifest. Preserve original ImageField values. Refuse any changed
   product/mapping or existing differing Cloudinary reference.
4. Verify all 14 HTTPS images, thumbnail/full-size rendering, alternate text,
   mobile layouts and upload permissions, then enable Cloudinary delivery and
   reopen the catalog. Keep original files available locally.

Do not run the old catalog bundle against a newer media schema: its field and
migration checks deliberately reject that mismatch. If integration order changes,
align a separate source copy and regenerate/review the catalog bundle first;
never quietly migrate or rewrite the owner's original SQLite database.

## Recovery

Before switching references, back up PostgreSQL and retain the old/new mapping
and source hashes. If rendering fails, turn off the new delivery feature and
correct/revert only the reviewed references. A local-path fallback on Render
does not restore durable images; use a safe placeholder or the previous working
Cloudinary references until fixed. Retain all original images and uploaded assets.

Do not mass-delete a Cloudinary folder during rollback. Any later cleanup must
identify only assets created by this batch, prove they are unreferenced, and get
separate deletion approval. After live edits, reconcile current image references
instead of restoring an old mapping over them.
