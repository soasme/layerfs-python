use layerfs_bridge::control::{SdkRefusal, SdkValue};
use pyo3::exceptions::{PyRuntimeError, PyTypeError, PyValueError};
use pyo3::prelude::*;
use pyo3::types::{PyBool, PyBytes, PyDict, PyInt, PyList, PyString, PyTuple};

pyo3::create_exception!(_native, LayerFSError, PyRuntimeError);

pub fn from_python(value: &Bound<'_, PyAny>, depth: usize) -> PyResult<SdkValue> {
    if depth > 16 {
        return Err(PyValueError::new_err("arguments exceed 16 nesting levels"));
    }
    Ok(if value.is_none() {
        SdkValue::Null
    } else if value.is_instance_of::<PyBool>() {
        SdkValue::Bool(value.extract()?)
    } else if value.is_instance_of::<PyInt>() {
        SdkValue::Int(value.extract()?)
    } else if value.is_instance_of::<PyString>() {
        SdkValue::Text(value.extract()?)
    } else if let Ok(bytes) = value.cast::<PyBytes>() {
        SdkValue::Bytes(bytes.as_bytes().to_vec())
    } else if let Ok(dict) = value.cast::<PyDict>() {
        let mut fields = Vec::with_capacity(dict.len());
        for (key, value) in dict.iter() {
            fields.push((key.extract::<String>()?, from_python(&value, depth + 1)?));
        }
        SdkValue::Map(fields)
    } else if value.is_instance_of::<PyList>() || value.is_instance_of::<PyTuple>() {
        let mut items = Vec::new();
        for item in value.try_iter()? {
            items.push(from_python(&item?, depth + 1)?);
        }
        SdkValue::List(items)
    } else {
        return Err(PyTypeError::new_err(
            "arguments must contain only None, bool, int, str, bytes, lists, tuples, and string-keyed dicts",
        ));
    })
}

pub fn to_python(py: Python<'_>, value: SdkValue) -> PyResult<Py<PyAny>> {
    Ok(match value {
        SdkValue::Null => py.None(),
        SdkValue::Bool(value) => value.into_pyobject(py)?.to_owned().into_any().unbind(),
        SdkValue::Int(value) => value.into_pyobject(py)?.into_any().unbind(),
        SdkValue::Text(value) => value.into_pyobject(py)?.into_any().unbind(),
        SdkValue::Bytes(value) => PyBytes::new(py, &value).into_any().unbind(),
        SdkValue::List(values) => {
            let result = PyList::empty(py);
            for value in values {
                result.append(to_python(py, value)?)?;
            }
            result.into_any().unbind()
        }
        SdkValue::Map(fields) => {
            let result = PyDict::new(py);
            for (key, value) in fields {
                result.set_item(key, to_python(py, value)?)?;
            }
            result.into_any().unbind()
        }
    })
}

pub fn error(py: Python<'_>, refusal: SdkRefusal) -> PyErr {
    let error = LayerFSError::new_err(format!("{}: {}", refusal.code, refusal.message));
    let instance = error.value(py);
    let fields = (|| -> PyResult<()> {
        instance.setattr("code", refusal.code)?;
        instance.setattr("message", refusal.message)?;
        instance.setattr("detail", to_python(py, refusal.detail)?)?;
        Ok(())
    })();
    match fields {
        Ok(()) => error,
        Err(error) => error,
    }
}
