"""Declared kernel preparation and the native --run_under executable."""

def _wrapper_impl(ctx):
    executable = ctx.actions.declare_file(ctx.label.name)
    ctx.actions.symlink(output = executable, target_file = ctx.file.launcher, is_executable = True)
    return [DefaultInfo(
        executable = executable,
        runfiles = ctx.runfiles(files = [ctx.file.script, ctx.file.launcher]),
    )]

agx_test_wrapper = rule(
    implementation = _wrapper_impl,
    executable = True,
    attrs = {
        "launcher": attr.label(allow_single_file = True),
        "script": attr.label(allow_single_file = True),
    },
)

def _kernel_impl(ctx):
    prefix = ctx.actions.declare_directory(ctx.label.name)
    ctx.actions.run_shell(
        inputs = depset(ctx.files.srcs + [ctx.file.builder]),
        tools = [ctx.file.uv, ctx.executable.agx],
        outputs = [prefix],
        command = '/usr/bin/python3 "$1" "$2" "$3" "$4" "$5"',
        arguments = [ctx.file.builder.path, ctx.file.uv.path,
                     ctx.executable.agx.path, ctx.file.manifest.path, prefix.path],
        mnemonic = "AgxKernelPython",
        progress_message = "Prepare agx kernel interpreter",
        # Only this action downloads Python/packages through agx bootstrap.
        execution_requirements = {"requires-network": "1"},
        env = {"PATH": "/usr/bin:/bin", "TZ": "UTC"},
    )
    return [DefaultInfo(files = depset([prefix]),
                        runfiles = ctx.runfiles(files = [prefix]))]

agx_kernel_python = rule(
    implementation = _kernel_impl,
    attrs = {
        "srcs": attr.label_list(allow_files = True),
        "manifest": attr.label(allow_single_file = True),
        "builder": attr.label(allow_single_file = True),
        "agx": attr.label(executable = True, cfg = "exec"),
        "uv": attr.label(allow_single_file = True, cfg = "exec"),
    },
)
