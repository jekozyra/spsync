import { defineRule } from "@oxlint/plugins";

/** Reject `for (;;)` loops in favor of an explicit infinite-loop condition. */
export const noEmptyForLoopHeaderRule = defineRule({
  meta: {
    type: "suggestion",
    docs: {
      description: "Disallow for loops whose initializer, condition, and update are all omitted.",
    },
    messages: {
      emptyForLoopHeader:
        "Replace `for (;;)` with `while (true)` so the infinite loop is explicit.",
    },
  },
  createOnce(context) {
    return {
      ForStatement(node) {
        if (node.init === null && node.test === null && node.update === null) {
          context.report({ node, messageId: "emptyForLoopHeader" });
        }
      },
    };
  },
});
