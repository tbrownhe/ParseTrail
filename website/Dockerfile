# Pin the multi-platform manifest so a release rebuild cannot silently change
# its web server base.
FROM nginx:1.28.0-alpine@sha256:30f1c0d78e0ad60901648be663a710bdadf19e4c10ac6782c235200619158284

# Copy website files to the appropriate directory
COPY ./website /usr/share/nginx/html

# Optional: Set permissions on the files
RUN chmod -R 755 /usr/share/nginx/html
