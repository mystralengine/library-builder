use std::ffi::{CStr, CString};
use std::os::raw::{c_char, c_int};
use std::ptr;

use anyhow::{Context, Result};
use swc_core::common::{
    errors::{Handler, EmitterWriter},
    FileName, SourceMap, Globals, GLOBALS, Mark,
    sync::Lrc,
};
use swc_core::ecma::codegen::{text_writer::JsWriter, Config, Emitter};
use swc_core::ecma::parser::{lexer::Lexer, Parser, StringInput, Syntax};
use swc_core::ecma::transforms::typescript::strip;
// use swc_core::ecma::visit::FoldWith; // fold_with replaced by apply

#[no_mangle]
pub unsafe extern "C" fn swc_transpile_ts(
    source: *const c_char,
    filename: *const c_char,
    _source_map_mode: *const c_char, // Unused for now
    out_js: *mut *mut c_char,
    out_sourcemap: *mut *mut c_char,
    out_error: *mut *mut c_char,
) -> c_int {
    // Helper to set error output
    let set_error = |err_msg: String| {
        let c_err = CString::new(err_msg).unwrap_or_default();
        *out_error = c_err.into_raw();
        *out_js = ptr::null_mut();
        *out_sourcemap = ptr::null_mut();
    };

    if source.is_null() || filename.is_null() {
        set_error("Source or filename is null".to_string());
        return 1;
    }

    let source_str = match CStr::from_ptr(source).to_str() {
        Ok(s) => s,
        Err(e) => {
            set_error(format!("Invalid source encoding: {}", e));
            return 1;
        }
    };

    let filename_str = match CStr::from_ptr(filename).to_str() {
        Ok(s) => s,
        Err(e) => {
            set_error(format!("Invalid filename encoding: {}", e));
            return 1;
        }
    };

    match transpile(source_str, filename_str) {
        Ok(js) => {
            let c_js = CString::new(js).unwrap_or_default();
            *out_js = c_js.into_raw();
            *out_sourcemap = ptr::null_mut(); // Not implemented yet
            *out_error = ptr::null_mut();
            0
        }
        Err(e) => {
            set_error(format!("{:#}", e));
            1
        }
    }
}

#[no_mangle]
pub unsafe extern "C" fn swc_free(ptr: *mut c_char) {
    if !ptr.is_null() {
        let _ = CString::from_raw(ptr);
    }
}

fn transpile(source: &str, filename: &str) -> Result<String> {
    let globals = Globals::new();
    GLOBALS.set(&globals, || {
        let cm: Lrc<SourceMap> = Default::default();
        
        let handler = Handler::with_emitter(
            true,
            false,
            Box::new(EmitterWriter::new(
                Box::new(std::io::stderr()),
                Some(cm.clone()),
                false,
                true,
            )),
        );

        let fm = cm.new_source_file(FileName::Real(filename.into()).into(), source.into());

        let mut syntax = Syntax::Typescript(Default::default());
        if let Syntax::Typescript(config) = &mut syntax {
            config.tsx = filename.ends_with(".tsx");
            config.decorators = true;
        }

        let lexer = Lexer::new(
            syntax,
            Default::default(),
            StringInput::from(&*fm),
            None,
        );

        let mut parser = Parser::new_from(lexer);

        let mut program = parser
            .parse_program()
            .map_err(|e| {
                e.into_diagnostic(&handler).emit();
                anyhow::anyhow!("Failed to parse TypeScript")
            })?;

        // Apply transforms
        // Use apply directly if supported by Program, or map over program
        program.apply(&mut strip(Mark::new(), Mark::new()));

        // Emit
        let mut buf = vec![];
        {
            let mut emitter = Emitter {
                cfg: Config::default(),
                cm: cm.clone(),
                comments: None,
                wr: JsWriter::new(cm.clone(), "\n", &mut buf, None),
            };

            emitter.emit_program(&program).context("Failed to emit JS")?;
        }

        let js = String::from_utf8(buf).context("Output is not valid UTF-8")?;
        Ok(js)
    })
}
