# Use the official nginx image
FROM nginx:latest

# Copy website files to the appropriate directory
COPY ./website /usr/share/nginx/html

# Optional: Set permissions on the files
RUN chmod -R 755 /usr/share/nginx/html
