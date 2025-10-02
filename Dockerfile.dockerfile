# Use the official Microsoft Playwright image for Python.
# This image comes with all necessary system dependencies and browser binaries pre-installed.
FROM mcr.microsoft.com/playwright/python:v1.44.0-jammy

# Set the working directory inside the container
WORKDIR /app

# Copy your requirements.txt file into the container
COPY requirements.txt .

# Install your Python dependencies.
# We don't need to run 'playwright install' because the browsers are already in the image.
RUN pip install --no-cache-dir -r requirements.txt

# Copy the rest of your application code into the container
COPY . .

# Expose the port your FastAPI application runs on (uvicorn default is 8000)
EXPOSE 8000

# The command to run your application when the container starts.
# This should match your current start command on Render.
CMD ["uvicorn", "server:app", "--host", "0.0.0.0", "--port", "8000"]
