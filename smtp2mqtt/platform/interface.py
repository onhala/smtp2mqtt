from abc import ABC, abstractmethod
from typing import Dict, Any

class PlatformAdapter(ABC):
    """Abstract Base Class defining the interface for platform-specific adapters."""
    
    @abstractmethod
    def initialize(self) -> None:
        """Runs initial environment patches or path setup."""
        pass

    @abstractmethod
    def load_config(self) -> Dict[str, Any]:
        """Loads configuration dictionary from environment, files, or platform config sources."""
        pass
    
    @abstractmethod
    def get_data_dir(self) -> str:
        """Returns the target directory for storing data such as email attachments."""
        pass
        
    @abstractmethod
    def get_log_dir(self) -> str:
        """Returns the directory where log files should be stored."""
        pass
