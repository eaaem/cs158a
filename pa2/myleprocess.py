"""
Performs the leader election algorithm using TCP and sockets.

Connects in a "ring": connects to a server as a client, and is connected to 
by a client as a server.

Once the process is signaled to start, it elects the greatest ID in the ring
as the leader.

This procedure loads IP addresses and port numbers from a file config.txt. The
first line of the file has this process' IP and port (to act as a server), while
the second line has another process' IP and port (to act as a client), with values
comma separated.

All steps are logged in a file, log.txt.

Run:
    python myleprocess.py

When all processes are ready to connect, press "Enter" as prompted.
"""

import sys
import uuid
import json
import socket
import logging
import time
import threading

from enum import StrEnum
from dataclasses import dataclass

BUFFER_SIZE = 1024

# Edit this variable to change the names of the config and log files used
FILE_SUFFIX = ""

LOG_NAME = f"log{FILE_SUFFIX}.txt"
CONFIG_FILE = f"config{FILE_SUFFIX}.txt"

logging.basicConfig(
    level=logging.INFO,
    format="%(message)s",
    handlers = [
        logging.FileHandler(LOG_NAME, mode="w"),
        logging.StreamHandler(sys.stdout)
    ]
)

class Message():
    """
    Defines a logging message in the leader election algorithm with the sender's
    UUID and a flag indicating the stage in the process (0 = still electing;
    1 = election finished).
    """
    uuid: uuid.UUID
    flag: int = 0

    def __init__(self, uuid, flag = 0):
        self.uuid = uuid
        self.flag = flag

    def __str__(self):
        return json.dumps({
            "uuid": str(self.uuid), 
            "flag": self.flag
        })

class ComparisonResult(StrEnum):
    """
    Defines the result of a comparison between IDs: greater, same, or less.
    """
    GREATER = "greater"
    SAME = "same"
    LESS = "less"

@dataclass
class MessageResult():
    """
    Contains the parsed result of a single message: ID, flag, and comparison result (to this process' ID).
    """
    uuid: uuid.UUID
    flag: int
    comparison_result: ComparisonResult


def load_config() -> tuple[str, int, str, int]:
    """
    Loads IP addresses and port numbers from config.txt.\n
    It is expected that the first line of the file contains `server_IP,server_port`,
    and the second line contains `client_IP,client_port`.\n
    Returns, in order: server IP, server port, client IP, client port
    """

    def split_line(line: str) -> tuple[str, int]:
        """
        Splits a config line along a comma, returning the IP address (before comma) and
        port (after comma).\n
        Returns, in order: IP, port
        """
        contents = line.split(",")

        # Throw an error if the line is misconfigured
        if (len(contents) != 2):
            raise ValueError(f"Config line \"{line}\" has incorrect comma separation")

        return contents[0], int(contents[1])

    # Get the IP addresses and port numbers
    with open(CONFIG_FILE, "r", encoding="utf-8") as config_file:
        server_ip, server_port = split_line(config_file.readline())
        client_ip, client_port = split_line(config_file.readline())

    return server_ip, server_port, client_ip, client_port


def send(client: socket.socket, msg: Message) -> None:
    """
    Sends the given message using the client socket and logs it.
    """
    logging.info(f"Sent: uuid={msg.uuid}, flag={msg.flag}")
    client.sendall(str(msg).encode())

def receive(connection: socket.socket) -> list[MessageResult]:
    """
    Receives a message, compares it to this process' flag and UUID, and logs the result.\n
    More than one message may be received at once, so the results are returned in a list.\n
    Returns the UUID, flag, and comparison result for each received message.\n
    If the connection is broken, `None` will be returned instead.
    """
    text = ""

    # Receive bytes from the buffer until the last letter of the message
    # is }, the end of message terminator
    # This makes sure that the entire message has been received
    while len(text) == 0 or text[-1] != '}':
        received = connection.recv(BUFFER_SIZE)

        # Connection has terminated
        if not received:
            return None

        text += received.decode()

    text_list = list()

    # If the client sends several messages quickly, they might get merged in the buffer
    # Split apart continuous messages to be parsed
    opening_index = text.find('{')
    starting_index = opening_index if opening_index != -1 else 0
    closing_index = text.find('}')
    while starting_index < closing_index and starting_index != -1 and closing_index != -1:
        text_list.append(json.loads(text[starting_index:(closing_index + 1)]))
        starting_index = closing_index + 1

        # If the message after } does not seem to start with a {, try finding it,
        # to find the correct portion of the message
        # Revert to the default (index of } + 1) if no { can be found
        if starting_index < len(text) and text[starting_index] != '{':
            opening_index = text.find('{', starting_index)
            starting_index = opening_index if opening_index != -1 else starting_index

        closing_index = text.find('}', starting_index + 1)

    # Parse each message
    result_list = list()
    for data in text_list:
        received_uuid = uuid.UUID(data["uuid"])

        # Check the comparison
        comparison_result = ComparisonResult.SAME
        if received_uuid > process_id:
            comparison_result = ComparisonResult.GREATER
        elif received_uuid < process_id:
            comparison_result = ComparisonResult.LESS

        # If this process has found the leader, add the leader UUID to the logging message
        leader_id_text = ""
        if process_flag == 1:
            leader_id_text = f", leader_id={leader_id}"

        logging.info(
            f"Received: uuid={data['uuid']}, flag={data['flag']}, {comparison_result}, "
            f"{process_flag}{leader_id_text}"
        )

        # If the received ID is smaller, report it as ignored
        if comparison_result == ComparisonResult.LESS:
            logging.info(f"Ignored: uuid={data['uuid']}")

        # Add the result
        result_list.append(MessageResult(uuid=received_uuid, flag=int(data['flag']), comparison_result=comparison_result))
    
    return result_list


def server_setup(server: socket.socket, server_ip: str, server_port: int, connection_list: list) -> None:
    """
    Sets up the server socket and gets a connection. Puts the connection in the first
    index of connection_list.\n
    Intended to be executed in a separate thread, so the program will not be blocked 
    while the server waits for the client to connect.
    """
    # Allow server reuse on stopping
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)

    # Bind server to the correct IP and port
    server.bind((server_ip, server_port))

    # Listen for 1 client
    server.listen(1)

    # Accept a connection
    connection, _ = server.accept()
    connection_list.append(connection)


# Generate this process' UUID
process_id = uuid.uuid4()
process_flag = 0

# Initialize the leader UUID to this UUID to start
leader_id = process_id

# Log the UUID on startup
logging.info(f"uuid={process_id}")

# Get the IP addresses and port numbers
server_ip, server_port, client_ip, client_port = load_config()

# Open both sockets
with (
    socket.socket(socket.AF_INET, socket.SOCK_STREAM) as server,
    socket.socket(socket.AF_INET, socket.SOCK_STREAM) as client
):
    connection_list = []
    
    # Start the server thread
    # A mutable connection_list is passed to store the connection socket,
    # which is opened in the thread
    server_thread = threading.Thread(
        target=server_setup,
        args=(server, server_ip, server_port, connection_list),
        daemon=True
    )
    server_thread.start()

    # Wait before trying to connect, so the server will be up
    time.sleep(1)

    # Block to wait until all processes/computers are ready
    input("Press Enter when everyone is ready.")

    # Connect the client
    client.connect((client_ip, client_port))

    # Block until the server has a client connected
    server_thread.join()

    # Get the client connection
    connection = connection_list[0]

    # Send the first message
    send(client, Message(leader_id))

    while True:
        # Receive all messages
        results = receive(connection)

        # If no result was found, report the connection as broken and end
        if results is None:
            print("Client connection broken; terminating")
            break

        # Loop through each result
        for result in results:
            # The sender has elected a leader; acknowledge it
            if result.flag == 1:
                # Only forward when getting the leader message for the first time,
                # to avoid infinite loops
                if process_flag != 1:
                    logging.info(f"Leader is {result.uuid}.")
                    send(client, Message(result.uuid, 1))
                    leader_id = result.uuid
                    process_flag = 1
            else:
                # Leader elected; forward the announcement
                if result.comparison_result == ComparisonResult.SAME:
                    leader_id = result.uuid
                    process_flag = 1
                    logging.info(f"Leader is decided to {leader_id}.")
                    send(client, Message(leader_id, 1))
                elif result.comparison_result == ComparisonResult.GREATER:
                    # Received ID is larger, forward it
                    send(client, Message(result.uuid))
