from __future__ import annotations

import inspect
from abc import ABC, abstractmethod
from base64 import b64decode
from enum import Enum
from pathlib import Path
from typing import TYPE_CHECKING, Any, Generic, Type, TypeVar

from ..cli import CLIBuilder
from ..ssh import SSHBashProcess, SSHClient, SSHLog, SSHPowerShellProcess, SSHProcess
from .logging import MultihostLogger
from .marks import TopologyMark

if TYPE_CHECKING:
    from .fixtures import MultihostFixture


class MultihostConfig(ABC):
    """
    Multihost configuration.
    """

    def __init__(self, confdict: dict[str, Any], *, logger: MultihostLogger, lazy_ssh: bool = False) -> None:
        self.logger: MultihostLogger = logger
        """Multihost logger"""

        self.lazy_ssh: bool = lazy_ssh
        """If True, hosts postpone connecting to ssh when the connection is first required"""

        self.domains: list[MultihostDomain] = []
        """Available domains"""

        if "domains" not in confdict:
            raise ValueError('"domains" property is missing in multihost configuration')

        for domain in confdict["domains"]:
            self.domains.append(self.create_domain(domain))

    @property
    def TopologyMarkClass(self) -> Type[TopologyMark]:
        """
        Class name of the type or subtype of :class:`TopologyMark`.
        """
        return TopologyMark

    @abstractmethod
    def create_domain(self, domain: dict[str, Any]) -> MultihostDomain:
        """
        Create new multihost domain from dictionary.

        :param domain: Domain in dictionary form.
        :type domain: dict[str, Any]
        :return: New multihost domain.
        :rtype: MultihostDomain
        """
        pass


ConfigType = TypeVar("ConfigType", bound=MultihostConfig)


class MultihostDomain(ABC, Generic[ConfigType]):
    """
    Multihost domain class.
    """

    def __init__(self, config: ConfigType, confdict: dict[str, Any]) -> None:
        if "type" not in confdict:
            raise ValueError('"type" property is missing in domain configuration')

        if "hosts" not in confdict:
            raise ValueError('"hosts" property is missing in domain configuration')

        self.config: ConfigType = config
        """Multihost configuration"""

        self.logger: MultihostLogger = config.logger
        """Multihost logger"""

        self.type: str = confdict["type"]
        """Domain type"""

        self.hosts: list[MultihostHost] = []
        """Available hosts in this domain"""

        for host in confdict["hosts"]:
            self.hosts.append(self.create_host(host))

    @property
    def roles(self) -> list[str]:
        """
        All roles available in this domain.

        :return: Role names.
        :rtype: list[str]
        """
        return sorted(set(x.role for x in self.hosts))

    def create_host(self, confdict: dict[str, Any]) -> MultihostHost:
        """
        Find desired host class by role.

        :param confdict: Host configuration as a dictionary.
        :type confdict: dict[str, Any]
        :raises ValueError: If role property is missing in the host configuration.
        :return: Host instance.
        :rtype: MultihostHost
        """
        if not confdict.get("role", None):
            raise ValueError('"role" property is missing in host configuration')

        role = confdict["role"]
        cls = self.role_to_host_type[role] if role in self.role_to_host_type else MultihostHost

        return cls(self, confdict)

    def create_role(self, mh: MultihostFixture, host: MultihostHost) -> MultihostRole:
        """
        Create role object from given host.

        :param mh: Multihost instance.
        :type mh: Multihost
        :param host: Multihost host instance.
        :type host: MultihostHost
        :raises ValueError: If unexpected role name is given.
        :return: Role instance.
        :rtype: MultihostRole
        """
        if host.role not in self.role_to_role_type:
            raise ValueError(f"Unexpected role: {host.role}")

        cls = self.role_to_role_type[host.role]
        return cls(mh, host.role, host)

    @property
    @abstractmethod
    def role_to_host_type(self) -> dict[str, Type[MultihostHost]]:
        """
        Map role to host class.

        :rtype: Class name.
        """
        pass

    @property
    @abstractmethod
    def role_to_role_type(self) -> dict[str, Type[MultihostRole]]:
        """
        Map role to role class.

        :rtype: Class name.
        """
        pass

    def hosts_by_role(self, role: str) -> list[MultihostHost]:
        """
        Return all hosts of the given role.

        :param role: Role name.
        :type role: str
        :return: List of hosts of given role.
        :rtype: list[MultihostHost]
        """
        return [x for x in self.hosts if x.role == role]


DomainType = TypeVar("DomainType", bound=MultihostDomain)


class MultihostHostOS(Enum):
    Linux = "linux"
    Windows = "windows"


class MultihostHost(Generic[DomainType]):
    """
    Base multihost host class.

    .. code-block:: yaml
        :caption: Example configuration in YAML format

        - hostname: dc.ad.test
          role: ad
          username: Administrator@ad.test
          password: vagrant
          config:
            binddn: Administrator@ad.test
            bindpw: vagrant
            client:
              ad_domain: ad.test
              krb5_keytab: /enrollment/ad.keytab
              ldap_krb5_keytab: /enrollment/ad.keytab

    * Required fields: ``hostname``, ``role``, ``username``, ``password``
    * Optional fields: ``config``
    """

    def __init__(self, domain: DomainType, confdict: dict[str, Any]):
        """
        :param domain: Multihost domain object.
        :type domain: DomainType
        :param confdict: Host configuration as a dictionary.
        :type confdict: dict[str, Any]
        :param shell: Shell used in SSH connection, defaults to '/usr/bin/bash -c'.
        :type shell: str
        """

        def is_present(property: str, confdict: dict[str, Any]) -> bool:
            if "/" in property:
                (key, subpath) = property.split("/", maxsplit=1)
                if not confdict.get(key, None):
                    return False

                return is_present(subpath, confdict[key])

            return property in confdict and confdict[property]

        for required in self.required_fields:
            if not is_present(required, confdict):
                raise ValueError(f'"{required}" property is missing in host configuration')

        # Required
        self.domain: DomainType = domain
        """Multihost domain."""

        self.logger: MultihostLogger = domain.logger
        """Multihost logger."""

        self.hostname: str = confdict["hostname"]
        """Host hostname."""

        self.role: str = confdict["role"]
        """Host role."""

        self.username: str = confdict["username"]
        """SSH username."""

        self.password: str = confdict["password"]
        """SSH passowrd."""

        # Optional
        self.ip: str = confdict["ip"] if "ip" in confdict else ""
        """Host IP address."""

        self.config: dict[str, Any] = confdict.get("config", {})
        """Custom configuration."""

        self.artifacts: list[str] = confdict.get("artifacts", [])
        """Host artifacts produced during tests."""

        # Not configurable
        self.shell: Type[SSHProcess] = SSHBashProcess
        """Shell used in SSH session."""

        # Determine host system and shell
        os = str(confdict.get("os", MultihostHostOS.Linux.value)).lower()
        try:
            self.os: MultihostHostOS = MultihostHostOS(os)
            """Host operating system."""
        except ValueError:
            raise ValueError(f'Value "{os}" is not supported in os field of host configuration')

        match self.os:
            case MultihostHostOS.Linux:
                self.shell = SSHBashProcess
            case MultihostHostOS.Windows:
                self.shell = SSHPowerShellProcess
            case _:
                raise ValueError(f"Unknown operating system: {self.os}")

        # SSH connection
        self.ssh: SSHClient = SSHClient(
            host=self._get_ssh_host(),
            user=self.username,
            password=self.password,
            logger=self.logger,
            shell=self.shell,
        )
        """SSH client."""

        # CLI Builder instance
        self.cli: CLIBuilder = CLIBuilder(self.ssh)
        """Command line builder."""

        # Connect to SSH unless lazy ssh is set
        if not self.domain.config.lazy_ssh:
            self.ssh.connect()

    @property
    def required_fields(self) -> list[str]:
        return ["hostname", "role", "username", "password"]

    def collect_artifacts(self, dest: str) -> None:
        """
        Collect test artifacts that were requested by the multihost configuration.

        :param dest: Destination directory, where the artifacts will be stored.
        :type dest: str
        """
        if not self.artifacts:
            return

        # Create output directory
        Path(dest).mkdir(parents=True, exist_ok=True)

        # Fetch artifacts
        match self.os:
            case MultihostHostOS.Linux:
                command = f"""
                    tmp=`mktemp /tmp/mh.host.artifacts.XXXXXXXXX`
                    tar -czvf "$tmp" {' '.join([f'$(compgen -G "{x}")' for x in self.artifacts])} &> /dev/null
                    base64 "$tmp"
                    rm -f "$tmp" &> /dev/null
                """
                ext = "tgz"
            case MultihostHostOS.Windows:
                raise NotImplementedError("Artifacts are not supported on Windows machine")
            case _:
                raise ValueError(f"Unknown operating system: {self.os}")

        result = self.ssh.run(command, log_level=SSHLog.Error)

        # Store artifacts in single archive
        with open(f"{dest}/{self.role}_{self.hostname}.{ext}", "wb") as f:
            f.write(b64decode(result.stdout))

    def pytest_setup(self) -> None:
        """
        Called once before execution of any tests.
        """
        pass

    def pytest_teardown(self) -> None:
        """
        Called once after all tests are finished.
        """
        pass

    def setup(self) -> None:
        """
        Called before execution of each test.
        """
        pass

    def teardown(self) -> None:
        """
        Called after execution of each test.
        """
        pass

    def _get_ssh_host(self) -> str:
        """
        Returns host for ssh with the priority ip, hostname
        :return: host to be used for ssh
        :rtype: str
        """
        if self.ip:
            return self.ip
        return self.hostname


HostType = TypeVar("HostType", bound=MultihostHost)


class MultihostRole(Generic[HostType]):
    """
    Base role class. Roles are the main interface to the remote hosts that can
    be directly accessed in test cases as fixtures.

    All changes to the remote host that were done through the role object API
    are automatically reverted when a test is finished.
    """

    def __init__(
        self,
        mh: MultihostFixture,
        role: str,
        host: HostType,
    ) -> None:
        self.mh: MultihostFixture = mh
        self.role: str = role
        self.host: HostType = host

    def setup(self) -> None:
        """
        Setup all :class:`MultihostUtility` objects
        that are attributes of this class.
        """
        MultihostUtility.SetupUtilityAttributes(self)

    def teardown(self) -> None:
        """
        Teardown all :class:`MultihostUtility` objects
        that are attributes of this class.
        """
        MultihostUtility.TeardownUtilityAttributes(self)

    def ssh(self, user: str, password: str, *, shell=SSHBashProcess) -> SSHClient:
        """
        Open SSH connection to the host as given user.

        :param user: Username.
        :type user: str
        :param password: User password.
        :type password: str
        :param shell: Shell that will run the commands, defaults to SSHBashProcess
        :type shell: str, optional
        :return: SSH client connection.
        :rtype: SSHClient
        """
        return SSHClient(self.host.hostname, user=user, password=password, shell=shell, logger=self.mh.logger)


class MultihostUtility(Generic[HostType]):
    """
    Base class for utility functions that operate on remote hosts, such as
    writing a file or managing SSSD.

    Instances of :class:`MultihostUtility` can be used in any role class which
    is a subclass of :class:`MultihostRole`. In this case, :func:`setup` and
    :func:`teardown` methods are called automatically when the object is created
    and destroyed to ensure proper setup and clean up on the remote host.
    """

    def __init__(self, host: HostType) -> None:
        """
        :param host: Remote host instance.
        :type host: HostType
        """
        self.host: HostType = host
        self.logger: MultihostLogger = self.host.logger

    def setup(self) -> None:
        """
        Setup object.
        """
        pass

    def teardown(self) -> None:
        """
        Teardown object.
        """
        pass

    @staticmethod
    def GetUtilityAttributes(o: object) -> dict[str, MultihostUtility]:
        """
        Get all attributes of the ``o`` that are instance of
        :class:`MultihostUtility`.

        :param o: Any object.
        :type o: object
        :return: Dictionary {attribute name: value}
        :rtype: dict[str, MultihostUtility]
        """
        return dict(inspect.getmembers(o, lambda attr: isinstance(attr, MultihostUtility)))

    @classmethod
    def SetupUtilityAttributes(cls, o: object) -> None:
        """
        Setup all :class:`MultihostUtility` objects attributes of the given
        object.

        :param o: Any object.
        :type o: object
        """
        for util in cls.GetUtilityAttributes(o).values():
            util.setup()

    @classmethod
    def TeardownUtilityAttributes(cls, o: object) -> None:
        """
        Teardown all :class:`MultihostUtility` objects attributes of the given
        object.

        :param o: Any object.
        :type o: object
        """
        errors = []
        for util in cls.GetUtilityAttributes(o).values():
            try:
                util.teardown()
            except Exception as e:
                errors.append(e)

        if errors:
            raise Exception(errors)
