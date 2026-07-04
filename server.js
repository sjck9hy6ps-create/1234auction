const key = `uploads/${Date.now()}-${Math.random().toString(36).slice(2)}-${filename}`;

const { data, error } = await supabase.storage.from(BUCKET).createSignedUploadUrl(key, 60);
if (error) throw error;

return res.json({ uploadUrl: data.signedUrl, key });
