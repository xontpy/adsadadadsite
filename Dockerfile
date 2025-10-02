# Use a base image with Python
FROM python:3.11-slim-buster

# Set the working directory
WORKDIR /app

# Install dependencies for Chrome
RUN apt-get update && apt-get install -y wget gnupg unzip --no-install-recommends

# Add Google's official GPG key
RUN wget -q -O - https://dl.google.com/linux/linux_signing_key.pub | apt-key add -
# Set up the repository
RUN sh -c 'echo "deb [arch=amd64] http://dl.google.com/linux/chrome/deb/ stable main" >> /etc/apt/sources.list.d/google.list'

# Install Google Chrome
RUN apt-get update && apt-get install -y google-chrome-stable --no-install-recommends

# Copy your application files
COPY requirements.txt .

# Install Python dependencies
# undetected-chromedriver will download the correct driver
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 8000

CMD ["uvicorn", "server:app", "--host", "0.0.0.0", "--port", "8000"]
