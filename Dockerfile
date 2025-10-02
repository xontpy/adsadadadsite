# Use the official Microsoft Playwright image for Python.
# This image comes with all necessary system dependencies and browser binaries pre-installed.
FROM mcr.microsoft.com/playwright/python:v1.44.0-jammy

# Set the working directory inside the container
WORKDIR /app

# Copy your requirements.txt file into the container
COPY requirements.txt .

# Install your Python dependencies.
# We set PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD=1 to explicitly prevent any browser download attempts,
# as they are already included in the base image.
RUN PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD=1 pip install --no-cache-dir -r requirements.txt

# Copy the rest of your application code into the container
COPY . .

# Expose the port your FastAPI application runs on (uvicorn default is 8000)
EXPOSE 8000

# The command to run your application when the container starts.
# This should match your current start command on Render.
CMD ["uvicorn", "server:app", "--host", "0.0.0.0", "--port", "8000"]
