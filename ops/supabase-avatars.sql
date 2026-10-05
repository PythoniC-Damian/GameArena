-- Review and run in your existing Supabase project only when enabling Storage.
-- Creates a new public-read avatar bucket. Existing bucket settings are preserved.
-- Uploads remain server-side through the service role; no anonymous write policy.
INSERT INTO storage.buckets (id, name, public, file_size_limit, allowed_mime_types)
VALUES ('avatars', 'avatars', true, 4194304, ARRAY['image/webp'])
ON CONFLICT (id) DO NOTHING;

SELECT id, public, file_size_limit, allowed_mime_types
FROM storage.buckets WHERE id = 'avatars';
