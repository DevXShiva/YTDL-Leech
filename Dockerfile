# Use a slim Python image
FROM python:3.10-slim

# Install system dependencies, including FFmpeg
RUN apt-get update && apt-get install -y \
    ffmpeg \
    --no-install-recommends \
    && rm -rf /var/lib/apt/lists/*

# Set the working directory
WORKDIR /app

# Copy the requirements file and install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy the rest of your application code
COPY . .

# Create a directory for downloads (important for ephemeral storage on Render)
RUN mkdir -p /app/downloads

# Command to run the bot
CMD ["python", "main.py"]
