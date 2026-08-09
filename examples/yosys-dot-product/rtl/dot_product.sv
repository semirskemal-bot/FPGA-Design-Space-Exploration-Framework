module dot_product #(
    parameter integer DATA_WIDTH = 8,
    parameter integer LANES = 4,
    parameter integer PIPELINE = 1,
    parameter integer ACC_WIDTH = (2 * DATA_WIDTH) + $clog2(LANES)
) (
    input  wire                              clk,
    input  wire                              reset,
    input  wire                              valid_in,
    input  wire [(LANES * DATA_WIDTH)-1:0]   a_flat,
    input  wire [(LANES * DATA_WIDTH)-1:0]   b_flat,
    output wire                              valid_out,
    output wire [ACC_WIDTH-1:0]              result
);
    integer lane;
    reg [ACC_WIDTH-1:0] sum_comb;

    always @* begin
        sum_comb = {ACC_WIDTH{1'b0}};
        for (lane = 0; lane < LANES; lane = lane + 1) begin
            sum_comb = sum_comb
                + ($unsigned(a_flat[(lane * DATA_WIDTH) +: DATA_WIDTH])
                *  $unsigned(b_flat[(lane * DATA_WIDTH) +: DATA_WIDTH]));
        end
    end

    generate
        if (PIPELINE == 0) begin : gen_combinational
            assign result = sum_comb;
            assign valid_out = valid_in;
        end else begin : gen_pipeline
            reg [ACC_WIDTH-1:0] data_pipe [0:PIPELINE-1];
            reg [PIPELINE-1:0] valid_pipe;
            integer stage;

            always @(posedge clk) begin
                if (reset) begin
                    valid_pipe <= {PIPELINE{1'b0}};
                    for (stage = 0; stage < PIPELINE; stage = stage + 1) begin
                        data_pipe[stage] <= {ACC_WIDTH{1'b0}};
                    end
                end else begin
                    data_pipe[0] <= sum_comb;
                    valid_pipe[0] <= valid_in;
                    for (stage = 1; stage < PIPELINE; stage = stage + 1) begin
                        data_pipe[stage] <= data_pipe[stage - 1];
                        valid_pipe[stage] <= valid_pipe[stage - 1];
                    end
                end
            end

            assign result = data_pipe[PIPELINE - 1];
            assign valid_out = valid_pipe[PIPELINE - 1];
        end
    endgenerate
endmodule
