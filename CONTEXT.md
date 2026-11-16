# Eva project context

- **GLM text model**: the configured text and tool model, defaulting to Z.AI's `glm-5.3-flash`.
- **Media input**: bounded image, video, and file content attached to a Discord message.
- **Reasoning continuity**: provider reasoning is private; it is cleared on a new user request and retained only across the immediate tool loop.
- **Image-generation provider**: the existing `IMAGE_API_BASE_URL` `/images` service, kept separate from GLM text analysis.
- **Ephemeral attachment context**: downloaded media exists only while building one request; history stores textual markers, never bytes or URLs.
