//! The kernel keeps upstream's orphan-journal variable under its exact name (PLAN D-26).

#[test]
fn the_kernel_keeps_the_variable_pa_core_journals_through() {
    assert_eq!(
        pa_types::fork_identity::KERNEL_ORPHAN_JOURNAL_KEY,
        pa_core::kernel::orphan_journal::ORPHAN_PROCESS_JOURNAL_ENV
    );
}
