class Size:
    """A size in bytes."""

    UNITS = ['B', 'KB', 'MB', 'GB', 'TB', 'PB', 'EB', 'ZB', 'YB']

    def __init__(self, size: int) -> None:
        """Initialize the size.

        Args:
            size (int): The size in bytes.
        """
        self.size = size

    def __str__(self) -> str:
        """Return the size as a string.

        Returns:
            str: The size as a string.
        """
        unit = 0
        while self.size >= 1024 and unit < len(Size.UNITS) - 1:
            self.size /= 1024
            unit += 1
        return f"{self.size:.2f} {Size.UNITS[unit]}"
