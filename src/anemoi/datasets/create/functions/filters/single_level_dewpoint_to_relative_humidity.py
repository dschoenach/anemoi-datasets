# (C) Copyright 2024 Anemoi contributors.
#
# This software is licensed under the terms of the Apache Licence Version 2.0
# which can be obtained at http://www.apache.org/licenses/LICENSE-2.0.
#
# In applying this licence, ECMWF does not waive the privileges and immunities
# granted to it by virtue of its status as an intergovernmental organisation
# nor does it submit to any jurisdiction.


from collections import defaultdict
from typing import Any
from typing import Dict

import earthkit.data as ekd
from earthkit.data.indexing.fieldlist import FieldArray
from earthkit.meteo import thermo

from .single_level_specific_humidity_to_relative_humidity import NewDataField


def execute(context: Any, input: ekd.FieldList, t: str, td: str, rh: str = "d") -> FieldArray:
    """Convert dewpoint on single levels to relative humidity.

    Args:
        context (Any): The context in which the function is executed.
        input (List[Any]): List of input fields.
        t (str): Temperature parameter.
        td (str): Dewpoint parameter.
        rh (str, optional): Relative humidity parameter. Defaults to "d".

    Returns:
        FieldArray: Array of fields with relative humidity.
    """
    result = FieldArray()
    params: tuple[str, str] = (t, td)
    pairs: Dict[tuple, Dict[str, Any]] = defaultdict(dict)

    # Gather all necessary fields
    for f in input:
        key = f.metadata(namespace="mars")
        param = key.pop("param")
        if param in params:
            key = tuple(key.items())

            if param in pairs[key]:
                raise ValueError(f"Duplicate field {param} for {key}")

            pairs[key][param] = f
            if param == t:
                result.append(f)
        # all other parameters
        else:
            result.append(f)

    for keys, values in pairs.items():
        # some checks

        if len(values) != 2:
            raise ValueError("Missing fields")

        t_values = values[t].to_numpy(flatten=True)
        td_values = values[td].to_numpy(flatten=True)
        # actual conversion from td --> rh
        rh_values = thermo.relative_humidity_from_dewpoint(t=t_values, td=td_values)
        result.append(NewDataField(values[td], rh_values, rh))

    return result


# class NewDataField:
#     def __init__(self, field: Any, data: NDArray[Any], new_name: str) -> None:
#         """
#         Initialize a NewDataField instance.

#         Args:
#             field (Any): The original field.
#             data (NDArray[Any]): The converted relative humidity data.
#             new_name (str): The new name for the field.
#         """
#         self.field = field
#         self.data = data
#         self.new_name = new_name

#     def to_numpy(self, *args: Any, **kwargs: Any) -> NDArray[Any]:
#         """
#         Convert the data to a numpy array.

#         Returns:
#             NDArray[Any]: The data as a numpy array.
#         """
#         return self.data

#     def metadata(self, key: Optional[str] = None, **kwargs: Any) -> Any:
#         """
#         Get metadata from the original field, with the option to rename the parameter.

#         Args:
#             key (Optional[str]): The metadata key.
#             **kwargs (Any): Additional keyword arguments.

#         Returns:
#             Any: The metadata value.
#         """
#         if key is None:
#             return self.field.metadata(**kwargs)

#         value = self.field.metadata(key, **kwargs)
#         if key == "param":
#             return self.new_name
#         return value

#     def __getattr__(self, name: str) -> Any:
#         """
#         Get an attribute from the original field.

#         Args:
#             name (str): The name of the attribute.

#         Returns:

#             Any: The attribute value.
#         """
#         return getattr(self.field, name)
