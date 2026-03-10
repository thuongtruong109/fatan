import csv, os
from typing import List, Any, Optional

class CSVHelper:
    @staticmethod
    def read_csv(file_path: str, delimiter: str = ',') -> List[List[str]]:
        """
        Read entire CSV file and return as list of lists

        Args:
            file_path: Path to the CSV file
            delimiter: CSV delimiter (default: ',')

        Returns:
            List of lists containing CSV data
        """
        if not os.path.exists(file_path):
            raise FileNotFoundError(f"File {file_path} not found")

        data = []
        with open(file_path, 'r', newline='', encoding='utf-8-sig') as file:
            reader = csv.reader(file, delimiter=delimiter)
            for row in reader:
                data.append(row)
        return data

    @staticmethod
    def write_csv(file_path: str, data: List[List[Any]], delimiter: str = ',') -> None:
        """
        Write entire data to CSV file

        Args:
            file_path: Path to the CSV file
            data: List of lists containing data to write
            delimiter: CSV delimiter (default: ',')
        """
        with open(file_path, 'w', newline='', encoding='utf-8-sig') as file:
            writer = csv.writer(file, delimiter=delimiter)
            for row in data:
                writer.writerow(row)

    @staticmethod
    def read_row(file_path: str, row_index: int, delimiter: str = ',') -> Optional[List[str]]:
        """
        Read a specific row from CSV file

        Args:
            file_path: Path to the CSV file
            row_index: Index of the row to read (0-based)
            delimiter: CSV delimiter (default: ',')

        Returns:
            List containing row data, or None if row doesn't exist
        """
        data = CSVHelper.read_csv(file_path, delimiter)
        if 0 <= row_index < len(data):
            return data[row_index]
        return None

    @staticmethod
    def read_column(file_path: str, col_index: int, delimiter: str = ',') -> Optional[List[str]]:
        """
        Read a specific column from CSV file

        Args:
            file_path: Path to the CSV file
            col_index: Index of the column to read (0-based)
            delimiter: CSV delimiter (default: ',')

        Returns:
            List containing column data, or None if column doesn't exist
        """
        data = CSVHelper.read_csv(file_path, delimiter)
        if not data:
            return None

        column = []
        for row in data:
            if col_index < len(row):
                column.append(row[col_index])
            else:
                column.append('')  # Pad with empty string if column doesn't exist in this row

        return column

    @staticmethod
    def write_row(file_path: str, row_index: int, row_data: List[Any], delimiter: str = ',') -> None:
        """
        Write data to a specific row in CSV file

        Args:
            file_path: Path to the CSV file
            row_index: Index of the row to write (0-based)
            row_data: Data to write to the row
            delimiter: CSV delimiter (default: ',')
        """
        data = CSVHelper.read_csv(file_path, delimiter)

        # Ensure we have enough rows
        while len(data) <= row_index:
            data.append([])

        # Ensure the row has enough columns
        while len(data[row_index]) < len(row_data):
            data[row_index].append('')

        # Write the row data
        for i, value in enumerate(row_data):
            if i < len(data[row_index]):
                data[row_index][i] = str(value)
            else:
                data[row_index].append(str(value))

        CSVHelper.write_csv(file_path, data, delimiter)

    @staticmethod
    def write_column(file_path: str, col_index: int, col_data: List[Any], delimiter: str = ',') -> None:
        """
        Write data to a specific column in CSV file

        Args:
            file_path: Path to the CSV file
            col_index: Index of the column to write (0-based)
            col_data: Data to write to the column
            delimiter: CSV delimiter (default: ',')
        """
        data = CSVHelper.read_csv(file_path, delimiter)

        # Ensure we have enough rows
        while len(data) < len(col_data):
            data.append([])

        # Write the column data
        for i, value in enumerate(col_data):
            # Ensure the row has enough columns
            while len(data[i]) <= col_index:
                data[i].append('')
            data[i][col_index] = str(value)

        CSVHelper.write_csv(file_path, data, delimiter)

    @staticmethod
    def append_row(file_path: str, row_data: List[Any], delimiter: str = ',') -> None:
        """
        Append a new row to CSV file

        Args:
            file_path: Path to the CSV file
            row_data: Data for the new row
            delimiter: CSV delimiter (default: ',')
        """
        data = CSVHelper.read_csv(file_path, delimiter)
        data.append([str(value) for value in row_data])
        CSVHelper.write_csv(file_path, data, delimiter)

    @staticmethod
    def get_csv_shape(file_path: str, delimiter: str = ',') -> tuple[int, int]:
        """
        Get the shape (rows, columns) of CSV file

        Args:
            file_path: Path to the CSV file
            delimiter: CSV delimiter (default: ',')

        Returns:
            Tuple of (number_of_rows, max_columns)
        """
        data = CSVHelper.read_csv(file_path, delimiter)
        if not data:
            return (0, 0)

        max_cols = max(len(row) for row in data) if data else 0
        return (len(data), max_cols)

    @staticmethod
    def update_cell(file_path: str, row_index: int, col_index: int, value: Any, delimiter: str = ',') -> None:
        """
        Update a specific cell in CSV file

        Args:
            file_path: Path to the CSV file
            row_index: Row index (0-based)
            col_index: Column index (0-based)
            value: Value to set
            delimiter: CSV delimiter (default: ',')
        """
        data = CSVHelper.read_csv(file_path, delimiter)

        # Ensure we have enough rows
        while len(data) <= row_index:
            data.append([])

        # Ensure the row has enough columns
        while len(data[row_index]) <= col_index:
            data[row_index].append('')

        data[row_index][col_index] = str(value)
        CSVHelper.write_csv(file_path, data, delimiter)

    @staticmethod
    def get_cell(file_path: str, row_index: int, col_index: int, delimiter: str = ',') -> Optional[str]:
        """
        Get value from a specific cell in CSV file

        Args:
            file_path: Path to the CSV file
            row_index: Row index (0-based)
            col_index: Column index (0-based)
            delimiter: CSV delimiter (default: ',')

        Returns:
            Cell value as string, or None if cell doesn't exist
        """
        row = CSVHelper.read_row(file_path, row_index, delimiter)
        if row and col_index < len(row):
            return row[col_index]
        return None