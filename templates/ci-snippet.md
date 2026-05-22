# CI: re-verify ticked tasks

Add this step to your CI workflow so a hand-ticked plan checkbox cannot pass
review. It re-runs the `verify` command of every ticked task in every plan;
a checkbox flipped without the work done fails its own verify.

```yaml
      - name: Re-verify ticked tasks in plans
        run: |
          for plan in docs/plans/*.md; do
            [ -e "$plan" ] || continue
            python scripts/harness/recheck_plan.py "$plan" || exit 1
          done
```
