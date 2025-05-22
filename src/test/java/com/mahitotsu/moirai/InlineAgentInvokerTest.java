package com.mahitotsu.moirai;

import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;

import software.amazon.awssdk.services.bedrockagentruntime.BedrockAgentRuntimeAsyncClient;

public class InlineAgentInvokerTest extends TestBase {

    @Autowired
    private BedrockAgentRuntimeAsyncClient bedrockAgentRuntimeAsyncClient;

    @Test
    public void testWithoutActionGroups() {

        final String answer = new InlineAgentInvoker().invoke(this.bedrockAgentRuntimeAsyncClient, null,
                """
                        あなたはユーザーの質問や依頼に丁寧かつ簡潔に答えるAIアシスタントです。
                        不足している情報がある場合、ユーザーに質問はせずに推測した情報を使って回答してください。
                        必要に応じてPythonコードを実行したり、指定されたツールを使って情報を取得してください。
                        """, null, null,
                """
                        今日は何月何日ですか。yyyy-MM-ddのフォーマットで回答してください。
                        """, null, null);

        System.out.println(answer);
    }
}