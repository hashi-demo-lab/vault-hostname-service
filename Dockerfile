# Use the official Python image from the Docker Hub
FROM python:3.9-slim

# Copy the CA certificate to the container
COPY kubernetes_ca.crt /usr/local/share/ca-certificates/kubernetes_ca.crt

# Update the system's CA certificates
RUN update-ca-certificates

# Set the working directory in the container
WORKDIR /app

# Copy the current directory contents into the container at /app
COPY . /app

# Install any needed packages specified in requirements.txt
RUN pip install --no-cache-dir Flask==2.2.5 hvac==2.3.0 flask-cors==3.0.10 Werkzeug==2.2.3

# Make port 5000 available to the world outside this container
EXPOSE 5000

# Run microservice.py when the container launches
CMD ["python", "microservice.py"]
