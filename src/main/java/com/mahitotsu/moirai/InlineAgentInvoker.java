package com.mahitotsu.moirai;

import java.util.Collection;
import java.util.LinkedList;
import java.util.Optional;
import java.util.Queue;
import java.util.UUID;
import java.util.function.Function;

import org.springframework.util.Assert;
import org.springframework.util.function.ThrowingFunction;

import software.amazon.awssdk.services.bedrockagentruntime.BedrockAgentRuntimeAsyncClient;
import software.amazon.awssdk.services.bedrockagentruntime.model.AgentActionGroup;
import software.amazon.awssdk.services.bedrockagentruntime.model.FunctionInvocationInput;
import software.amazon.awssdk.services.bedrockagentruntime.model.FunctionResult;
import software.amazon.awssdk.services.bedrockagentruntime.model.InlineSessionState;
import software.amazon.awssdk.services.bedrockagentruntime.model.InvocationResultMember;
import software.amazon.awssdk.services.bedrockagentruntime.model.InvokeInlineAgentRequest;
import software.amazon.awssdk.services.bedrockagentruntime.model.InvokeInlineAgentResponseHandler;
import software.amazon.awssdk.services.bedrockagentruntime.model.InvokeInlineAgentResponseHandler.Visitor;
import software.amazon.awssdk.services.bedrockagentruntime.model.ReturnControlResults;

public class InlineAgentInvoker {

    public String invoke(final BedrockAgentRuntimeAsyncClient client, final String foundationModel,
            final String instruction, final Collection<AgentActionGroup> actionGroups, final UUID sessionId,
            final String inputText, final ThrowingFunction<FunctionInvocationInput, FunctionResult> inputHandler,
            final Function<Exception, FunctionResult> errorHandler) {

        Assert.notNull(client, "client must not be null");
        Assert.notNull(instruction, "instruction must not be null");
        Assert.notNull(inputText, "inputText must not be null");

        final String sessionIdValue = (sessionId == null ? UUID.randomUUID().toString() : sessionId.toString());
        final Queue<ReturnControlResults> returnControlResults = new LinkedList<>();
        final StringBuilder output = new StringBuilder();

        do {
            client.invokeInlineAgent(
                    InvokeInlineAgentRequest.builder()
                            .foundationModel(foundationModel != null ? inputText : "apac.amazon.nova-micro-v1:0")
                            .actionGroups(actionGroups)
                            .instruction(instruction)
                            .sessionId(sessionIdValue)
                            .inputText(returnControlResults.isEmpty() ? inputText : null)
                            .inlineSessionState(Optional.ofNullable(returnControlResults.poll())
                                    .map(result -> InlineSessionState.builder()
                                            .invocationId(result.invocationId())
                                            .returnControlInvocationResults(result.returnControlInvocationResults())
                                            .build())
                                    .orElse(null))
                            .build(),
                    InvokeInlineAgentResponseHandler.builder()
                            .onEventStream(events -> events.subscribe(subscriber -> subscriber.accept(Visitor.builder()
                                    .onChunk(chunk -> {
                                        output.append(chunk.bytes().asUtf8String());
                                    })
                                    .onReturnControl(payload -> {
                                        final Collection<InvocationResultMember> results = payload.invocationInputs()
                                                .stream()
                                                .map(input -> input.functionInvocationInput())
                                                .map(input -> {
                                                    try {
                                                        return inputHandler.applyWithException(input);
                                                    } catch (Exception e) {
                                                        if (errorHandler != null) {
                                                            return errorHandler.apply(e);
                                                        } else {
                                                            throw new IllegalStateException(e);
                                                        }
                                                    }
                                                })
                                                .map(result -> InvocationResultMember.builder()
                                                        .functionResult(result)
                                                        .build())
                                                .toList();
                                        returnControlResults.offer(ReturnControlResults.builder()
                                                .invocationId(payload.invocationId())
                                                .returnControlInvocationResults(results)
                                                .build());
                                    })
                                    .build())))
                            .build())
                    .join();
        } while (returnControlResults.isEmpty() == false);

        return output.toString();
    }
}
