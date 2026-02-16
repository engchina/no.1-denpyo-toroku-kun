class Response:
    """Standard response wrapper for API responses."""

    def __init__(self):
        self.data = None
        self.error_messages = []
        self.warning_messages = []

    def set_data(self, data):
        """Set the response data."""
        self.data = data

    def add_error_message(self, message):
        """Add an error message."""
        self.error_messages.append(message)

    def add_warning_message(self, message):
        """Add a warning message."""
        self.warning_messages.append(message)

    def get_result(self):
        """Get the formatted result dictionary."""
        result = {}

        if self.data is not None:
            result["data"] = self.data

        if self.error_messages:
            result["errorMessages"] = self.error_messages

        if self.warning_messages:
            result["warningMessages"] = self.warning_messages

        return result
