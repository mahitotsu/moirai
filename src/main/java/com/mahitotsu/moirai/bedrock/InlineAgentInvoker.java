package com.mahitotsu.moirai.bedrock;

import java.util.Collection;
import java.util.HashSet;
import java.util.LinkedList;
import java.util.Optional;
import java.util.Queue;
import java.util.UUID;
import java.util.function.Function;
import java.util.stream.Collectors;

import org.springframework.util.Assert;
import org.springframework.util.function.ThrowingFunction;

import lombok.Data;
import software.amazon.awssdk.services.bedrockagentruntime.BedrockAgentRuntimeAsyncClient;
import software.amazon.awssdk.services.bedrockagentruntime.model.ActionGroupExecutor;
import software.amazon.awssdk.services.bedrockagentruntime.model.AgentActionGroup;
import software.amazon.awssdk.services.bedrockagentruntime.model.CustomControlMethod;
import software.amazon.awssdk.services.bedrockagentruntime.model.FunctionDefinition;
import software.amazon.awssdk.services.bedrockagentruntime.model.FunctionInvocationInput;
import software.amazon.awssdk.services.bedrockagentruntime.model.FunctionResult;
import software.amazon.awssdk.services.bedrockagentruntime.model.FunctionSchema;
import software.amazon.awssdk.services.bedrockagentruntime.model.InlineAgentReturnControlPayload;
import software.amazon.awssdk.services.bedrockagentruntime.model.InlineSessionState;
import software.amazon.awssdk.services.bedrockagentruntime.model.InvocationResultMember;
import software.amazon.awssdk.services.bedrockagentruntime.model.InvokeInlineAgentRequest;
import software.amazon.awssdk.services.bedrockagentruntime.model.InvokeInlineAgentResponseHandler;
import software.amazon.awssdk.services.bedrockagentruntime.model.InvokeInlineAgentResponseHandler.Visitor;
import software.amazon.awssdk.services.bedrockagentruntime.model.ParameterDetail;
import software.amazon.awssdk.services.bedrockagentruntime.model.ReturnControlResults;

@Data
public class InlineAgentInvoker {

    private BedrockAgentRuntimeAsyncClient bedrockAgentRuntimeAsyncClient;

    private Function<String, InlineAgentConfig> agentConfigLookup;

    private Function<String, ActionGroupConfig> actionGroupConfigLookup;

    private ThrowingFunction<FunctionInvocationInput, FunctionResult> functionInvoker;

    private Function<Exception, FunctionResult> errorHandler;

    private InlineAgentConfig lookupAgentConfig(String agentName) {
        return this.agentConfigLookup != null ? this.agentConfigLookup.apply(agentName) : null;
    }

    private ActionGroupConfig lookupActionGroupConfig(String actionGroupName) {
        return this.actionGroupConfigLookup != null ? this.actionGroupConfigLookup.apply(actionGroupName) : null;
    }

    private FunctionResult invokeFunction(FunctionInvocationInput invocationInput) throws Exception {
        return Optional.of(this.functionInvoker).get().applyWithException(invocationInput);
    }

    private FunctionResult handleFunctionInvocationError(Exception error) {
        return Optional.ofNullable(this.errorHandler).map(h -> h.apply(error))
                .orElseThrow(() -> new IllegalStateException(error));
    }

    private AgentActionGroup buildAgentActionGroup(final ActionGroupConfig actionGroupConfig) {

        return AgentActionGroup.builder()
                .actionGroupName(actionGroupConfig.getName())
                .description(actionGroupConfig.getDescription())
                .actionGroupExecutor(ActionGroupExecutor
                        .fromCustomControl(CustomControlMethod.RETURN_CONTROL))
                .functionSchema(FunctionSchema.builder()
                        .functions(actionGroupConfig.getFunctions().entrySet().stream()
                                .map(entry -> FunctionDefinition.builder()
                                        .name(entry.getKey())
                                        .description(entry.getValue().getDescription())
                                        .parameters(entry.getValue().getParameters().entrySet().stream()
                                                .collect(Collectors.toMap(i -> i.getKey(),
                                                        i -> ParameterDetail.builder()
                                                                .type(i.getValue().getType())
                                                                .description(i.getValue().getDescription())
                                                                .required(i.getValue().isRequired())
                                                                .build())))
                                        .build())
                                .toList())
                        .build())
                .build();
    }

    private InlineSessionState nextInlineSessionState(final Queue<ReturnControlResults> returnControlResults) {

        return Optional.ofNullable(returnControlResults.poll())
                .map(result -> InlineSessionState.builder()
                        .invocationId(result.invocationId())
                        .returnControlInvocationResults(result.returnControlInvocationResults())
                        .build())
                .orElse(null);
    }

    private ReturnControlResults handleInlineAgentReturnControlPayload(final InlineAgentReturnControlPayload payload) {

        return ReturnControlResults.builder()
                .invocationId(payload.invocationId())
                .returnControlInvocationResults(payload.invocationInputs().stream()
                        .map(input -> {
                            try {
                                return this.invokeFunction(input.functionInvocationInput());
                            } catch (Exception e) {
                                return this.handleFunctionInvocationError(e);
                            }
                        })
                        .map(result -> InvocationResultMember.builder()
                                .functionResult(result)
                                .build())
                        .toList())
                .build();
    }

    public String invoke(final String agentName, final UUID sessionId, final String inputText) {

        final BedrockAgentRuntimeAsyncClient client = this.getBedrockAgentRuntimeAsyncClient();
        Assert.notNull(client, "client must not be null");
        Assert.notNull(inputText, "inputText must not be null");

        final InlineAgentConfig agentConfig = this.lookupAgentConfig(agentName);
        if (agentConfig == null) {
            throw new IllegalStateException("No agent with the specified name was found.");
        }
        final Collection<AgentActionGroup> actionGroups = new HashSet<>();
        for (final String actionGroupName : agentConfig.getActionGroupNames()) {
            final ActionGroupConfig actionGroupConfig = this.lookupActionGroupConfig(actionGroupName);
            if (actionGroupConfig == null) {
                throw new IllegalStateException("No actionGroup with the specified name was found.");
            }
            actionGroups.add(this.buildAgentActionGroup(actionGroupConfig));
        }

        final String sessionIdValue = (sessionId == null ? UUID.randomUUID().toString() : sessionId.toString());
        final Queue<ReturnControlResults> returnControlResults = new LinkedList<>();
        final StringBuilder output = new StringBuilder();

        do {
            client.invokeInlineAgent(
                    InvokeInlineAgentRequest.builder()
                            .foundationModel(agentConfig.getFoundationModel())
                            .instruction(agentConfig.getInstruction())
                            .actionGroups(actionGroups)
                            .sessionId(sessionIdValue)
                            .inputText(returnControlResults.isEmpty() ? inputText : null)
                            .inlineSessionState(this.nextInlineSessionState(returnControlResults))
                            .build(),
                    InvokeInlineAgentResponseHandler.builder()
                            .onEventStream(events -> events.subscribe(subscriber -> subscriber.accept(Visitor.builder()
                                    .onChunk(chunk -> output.append(chunk.bytes().asUtf8String()))
                                    .onReturnControl(payload -> returnControlResults
                                            .offer(this.handleInlineAgentReturnControlPayload(payload)))
                                    .build())))
                            .build())
                    .join();
        } while (returnControlResults.isEmpty() == false);

        return output.toString();
    }
}
