FROM apify/actor-python:3.11

# Copy package files
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# Copy source code
COPY src ./src
COPY .actor/actor.json ./

# Set run command
CMD ["python", "-m", "my_actor"]
