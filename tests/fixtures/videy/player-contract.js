// Sanitized excerpt from Videy's public bundle fetched 2026-10-16.
const id = searchParams.get("id");
const extension = !id || id.length === 8 || (id.length === 9 && id.endsWith("1"))
  ? "mp4"
  : id.length === 9 && id.endsWith("2") ? "mov" : "mp4";
const media = id ? `https://cdn.videy.co/${id}.${extension}` : "";
