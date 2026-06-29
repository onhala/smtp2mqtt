# Contributing to smtp2mqtt

First of all, thank you for taking the time to contribute to `smtp2mqtt`! This project is designed to be a premium, modern, and reliable gateway for home automation environments.

Here is a guide to help you set up the development environment, run tests, simulate interactions, and submit your contributions.

## Development Environment Setup

1. **Clone the repository**:
   ```bash
   git clone https://github.com/onhala/smtp2mqtt.git
   cd smtp2mqtt
   ```

2. **Create and activate a virtual environment**:
   ```bash
   python -m venv .venv
   source .venv/bin/activate
   ```

3. **Install dependencies**:
   ```bash
   pip install --upgrade pip
   pip install -r requirements.txt
   pip install -r requirements-dev.txt
   ```

## Running the Automated Test Suite

We use `pytest` for automated testing. Ensure your changes do not break existing behaviors and maintain our high test coverage.

- **Run all tests**:
   ```bash
   pytest tests/ -v
   ```

- **Run tests with coverage report**:
   ```bash
   pytest --cov=. --cov-report=term-missing tests/
   ```

## Local Simulation & Interactive Testing

For hands-on testing without an active MQTT broker or real security cameras, we provide an interactive simulation environment in `scratch/simulate.py`.

1. **Start the simulation environment**:
   ```bash
   python scratch/simulate.py
   ```
   This spins up a mock MQTT broker listening on port `1883` in a background thread and opens an interactive prompt.

2. **Run the gateway**:
   In another terminal tab, run:
   ```bash
   python smtp2mqtt.py
   ```
   It will automatically connect to the mock broker and start listening on port `1025` for SMTP transactions.

3. **Send mock emails**:
   Go back to the simulation terminal and press **`E`** to send a mock email trigger (including a sample JPEG snapshot). Watch the gateway parse the email, save the attachment, publish `ON` to the broker, and automatically publish `OFF` after the configured reset delay.

4. **Exit the simulation**:
   Press **`Q`** in the simulation console to cleanly stop the mock broker.

## Code Guidelines

- **Asynchronous Code**: This project is fully asynchronous using `asyncio` and `aiosmtpd`. Avoid using synchronous blocking operations (such as `time.sleep` or blocking socket connections) in the main thread. Use `asyncio.to_thread` for blocking IO.
- **Code Style**: Keep code readable and documented with helpful docstrings and comments.
- **Error Handling**: Use robust exception handling to ensure that mail parsing issues do not crash the entire gateway.

## Submission Process

1. Create a descriptive feature branch (e.g., `feature/custom-web-port`).
2. Implement your changes, ensuring tests pass and coverage is maintained.
3. Submit a Pull Request targeting the `master` or `main` branch.
4. Fill out the provided Pull Request template completely.
