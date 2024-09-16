import sys


class Progress:
    """A progress bar."""

    BAR_LENGTH = 4

    def __init__(self, progress: float) -> None:
        """Initialize the progress bar.

        Args:
            progress (float): The progress between 0 and 1.
        """
        self.progress = progress

    @property
    def progress(self) -> float:
        return self._progress

    @progress.setter
    def progress(self, progress: float):
        if not 0 <= progress <= 1:
            print(f"warning: progress {progress} is not between 0 and 1", flush=True, file=sys.stderr)
            progress = max(0, min(progress, 1))
        self._progress = progress

    def __str__(self) -> str:
        """Return the progress bar as a string.

        Returns:
            str: The progress bar as a string.
        """
        bar = '━' * int(Progress.BAR_LENGTH * self.progress) \
            + ('╾' if self.progress * Progress.BAR_LENGTH % 1 >= 0.5 else '─') \
            + '─' * Progress.BAR_LENGTH
        bar = bar[:Progress.BAR_LENGTH]
        return f"{bar} {100*self.progress:.2f}%"
